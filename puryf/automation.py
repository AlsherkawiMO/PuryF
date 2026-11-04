# SPDX-License-Identifier: MIT
"""Explicit local watch folders, interval schedules and controllable background queue."""
import json
import os
from pathlib import Path
import threading
import time
import uuid
from .sdk import Client
from .state import content_hash
from .explorer import InstanceLock
from .jobs import TERMINAL

class Runner:
    def __init__(self,config):
        if not isinstance(config,dict) or set(config)-{'state_dir','watches','schedules','plugins','poll_seconds'}:raise ValueError('Invalid automation config')
        self.root=Path(config['state_dir']).expanduser().resolve();self.client=Client(self.root)
        self.lock=InstanceLock(self.root/'automation-owner')
        if not self.lock.acquire():self.client.close();raise ValueError('Another background queue owns this state directory')
        with self.client.store.connect() as db:db.execute("UPDATE automation SET state='interrupted' WHERE state='pending'")
        from .explorer import runtime_dir
        self.registration=InstanceLock(runtime_dir().parent/'IntegrationHosts'/uuid.uuid4().hex);self.registration.acquire()
        self.config=config;self.stable={};self.jobs={};self.closed=False
        self.control_seen=None
        try:
            from .extensions import load
            for plugin in config.get('plugins',[]):load(plugin)
            names=set()
            for rule in config.get('watches',[]):
                if not isinstance(rule,dict) or set(rule)-{'name','folder','output','recursive','preset','options'}:raise ValueError('Invalid watch fields')
                if not isinstance(rule.get('options',{}),dict) or set(rule.get('options',{}))&{'output_folder','source_root','preserve_folders'}:raise ValueError('Watch output/source roots must be configured in the rule, not options')
                if not rule.get('name') or rule['name'] in names:raise ValueError('Watch names must be unique')
                names.add(rule['name'])
                folder=Path(rule['folder']).resolve();output=Path(rule['output']).resolve()
                if not folder.is_dir() or output==folder:raise ValueError('Watch input must exist; output must differ')
            for rule in config.get('schedules',[]):
                if not isinstance(rule,dict) or set(rule)-{'name','every_seconds','request'} or not rule.get('name') or type(rule.get('every_seconds')) is not int or rule['every_seconds']<1:raise ValueError('Schedules require a name, positive every_seconds, request')
        except Exception:
            self.close();raise
    def tick(self,now=None):
        from .cli import expand_inputs
        now=time.time() if now is None else now
        control=self.root/'control.json'
        if control.exists():
            try:
                command=json.loads(control.read_text());nonce=command['nonce']
                if nonce!=self.control_seen:
                    self.control_seen=nonce
                    if command['action']=='pause':self.client.pause()
                    elif command['action']=='resume':self.client.resume()
                    elif command['action']=='stop':self.closed=True
                    elif command['action']=='retry':
                        with self.client.store.connect() as db:db.execute("DELETE FROM automation WHERE state IN ('failed','interrupted')")
            except (ValueError,KeyError):pass
        for jid,(rule,path,digest) in list(self.jobs.items()):
            result=self.client.service.get_job(jid)
            if result['status'] in TERMINAL:
                with self.client.store.connect() as db:db.execute('UPDATE automation SET state=? WHERE rule=? AND path=? AND digest=?',('done' if result['status'] in ('succeeded','skipped') else 'failed',rule,path,digest))
                del self.jobs[jid]
        if self.closed:return
        for rule in self.config.get('watches',[]):
            folder=Path(rule['folder']).resolve();output=Path(rule['output']).resolve()
            paths,_=expand_inputs([str(folder)],rule.get('recursive',False),str(output))
            for value in paths:
                path=Path(value);stat=path.stat();signature=(stat.st_size,stat.st_mtime_ns)
                marker=(rule['name'],str(path))
                if self.stable.get(marker)!=signature:self.stable[marker]=signature;continue
                digest=content_hash(path)
                with self.client.store.connect() as db:record=db.execute('SELECT digest,state FROM automation WHERE rule=? AND path=?',marker).fetchone()
                # Failure does not spin forever; edit content or remove the state row to retry.
                if record and record[0]==digest and record[1]!='interrupted':continue
                options={'output_folder':str(output),'source_root':str(folder),'preserve_folders':True,'naming_pattern':'{stem}-{hash8}',**rule.get('options',{})}
                handle=self.client.convert([path],options,rule.get('preset'))
                with self.client.store.connect() as db:db.execute('INSERT OR REPLACE INTO automation VALUES (?,?,?,?,?)',(*marker,digest,'pending',handle.id))
                self.jobs[handle.id]=(*marker,digest)
        for schedule in self.config.get('schedules',[]):
            bucket=int(now//schedule['every_seconds'])
            with self.client.store.connect() as db:
                fresh=db.execute('INSERT OR IGNORE INTO schedules VALUES (?,?)',(schedule['name'],bucket)).rowcount
                db.execute('DELETE FROM schedules WHERE bucket<? AND name=?',(bucket-1000,schedule['name']))
            if fresh:self.submit_request(schedule['request'])
    def submit_request(self,file):
        from .cli import build_parser,normalize,expand_inputs
        args=build_parser().parse_args(['request',str(file)])
        args.state_dir=str(self.root);data=normalize(args);cmd=data['command']
        if cmd=='convert':
            paths,_=expand_inputs(data['inputs'],data.get('recursive',False),data['_options'].output_folder)
            return self.client.convert(paths,data['_options'])
        if cmd=='merge':return self.client.service.submit_merge(data['inputs'],data['output'],data['_options'],passwords={p:data['_input_password'] for p in data['inputs']})
        if cmd=='split':return self.client.service.submit_split(data['inputs'][0],data['_options'],output_file=data.get('output'),output_dir=data.get('output_dir'),page_ranges=data.get('pages'),every_n=data.get('every'),password=data['_input_password'])
        raise ValueError('Schedules require convert, merge or split requests')
    def close(self):
        self.client.close();self.lock.close();self.registration.close()
        try:self.registration.path.unlink();self.registration.path.parent.rmdir()
        except OSError:pass

def control(root,action):
    if action not in ('pause','resume','stop','retry'):raise ValueError('Invalid background action')
    root=Path(root).resolve()
    if not (root/'automation-owner'/'instance.lock').exists():raise ValueError('No background queue state found')
    temporary=root/('control-'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps({'action':action,'nonce':uuid.uuid4().hex}))
    temporary.replace(root/'control.json')

def run(file):
    config=json.loads(Path(file).read_text(encoding='utf-8-sig'))
    runner=Runner(config)
    try:
        while not runner.closed:
            runner.tick()
            time.sleep(max(.2,min(float(config.get('poll_seconds',2)),60)))
    except KeyboardInterrupt:pass
    finally:runner.close()

# SPDX-License-Identifier: MIT
"""Persistent, tenant-scoped gateway shared by stdio MCP and HTTP adapters.

Single-host alpha. Filesystem separation is not a hostile-document OS sandbox.
"""
import base64
from dataclasses import replace
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
import zipfile

from .access import APIError, FolderPolicy, fail, integer, object_fields
from .engine import ALL_EXTS, OFFICE_EXTS, ConverterEngine, Image, PdfReader
from .explorer import InstanceLock,runtime_dir
from .jobs import ConversionService, TERMINAL
from .options import ConversionOptions

HOSTED_FORMATS={'.txt','.md','.png','.jpg','.jpeg','.bmp','.gif','.tif','.tiff','.webp','.pdf'}

def encoded(data):return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()

def filename(value):
    if not isinstance(value,str) or not 1<=len(value)<=120 or value in ('.','..') or any(ord(c)<32 or c in '<>:"/\\|?*' for c in value) or value.endswith((' ','.')):
        fail(400,'invalid_filename','A simple filename is required')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'{p}{n}' for p in ('COM','LPT') for n in range(1,10)]}:
        fail(400,'invalid_filename','Reserved filename')
    return value

class Gateway:
    def __init__(self,config):
        self.config=config;self.root=config['data_dir'];self.lock=threading.RLock()
        self.owner=InstanceLock(self.root/'host')
        if not self.owner.acquire():raise RuntimeError('Another integration server owns this data directory')
        marker=self.root/'puryf-server.marker'
        # Host lock is the only permitted pre-existing item on first use.
        if not marker.exists() and any(p.name!='host' for p in self.root.iterdir()):
            self.owner.close();raise ValueError('Use an empty dedicated integration data directory')
        if marker.exists() and marker.read_text()!='PuryF gateway v1':
            self.owner.close();raise ValueError('Invalid gateway marker')
        marker.write_text('PuryF gateway v1')
        try:os.chmod(self.root,0o700)
        except OSError:pass
        for folder in ('uploads','work'): (self.root/folder).mkdir(exist_ok=True)
        secret_file=self.root/'signing.key'
        if not secret_file.exists():
            fd=os.open(secret_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(secrets.token_bytes(32))
        if secret_file.is_symlink():raise ValueError('Signing key may not be linked')
        self.secret=secret_file.read_bytes()
        if len(self.secret)!=32:raise ValueError('Invalid signing key')
        self.db=sqlite3.connect(self.root/'gateway.sqlite3',check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,owner TEXT,path TEXT,name TEXT,size INTEGER,created REAL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT,core TEXT,created REAL,finished REAL,status TEXT,
 request_hash TEXT,ikey TEXT,inputs TEXT,snapshot TEXT,hook TEXT,UNIQUE(owner,ikey));
CREATE TABLE IF NOT EXISTS usage(owner TEXT,kind TEXT,stamp REAL,amount INTEGER);
CREATE INDEX IF NOT EXISTS usage_window ON usage(owner,kind,stamp);
CREATE TABLE IF NOT EXISTS hooks(job TEXT PRIMARY KEY,owner TEXT,preset TEXT,body TEXT,attempts INTEGER,next REAL,status TEXT);
''')
        for row in self.db.execute("SELECT * FROM jobs WHERE status NOT IN ('succeeded','failed','partial','skipped','cancelled')").fetchall():
            snapshot={'id':row['id'],'status':'failed','progress':{'completed':0,'total':0,'percent':0,'current':''},'outputs':[],
                      'errors':[{'code':'server_restarted','message':'Server restarted; job was not automatically repeated'}]}
            self.db.execute('UPDATE jobs SET status=?,finished=?,snapshot=? WHERE id=?',('failed',time.time(),json.dumps(snapshot),row['id']))
        self.db.commit()
        self.db.execute("UPDATE hooks SET status='pending' WHERE status='sending'");self.db.commit()
        self.service=ConversionService(reports_dir=self.root/'reports')
        self.registration=InstanceLock(runtime_dir().parent/'IntegrationHosts'/uuid.uuid4().hex)
        if not self.registration.acquire():
            self.service.close()
            self.db.close()
            self.owner.close()
            raise RuntimeError('Cannot register integration host')
        self.stop=threading.Event();self.monitor=threading.Thread(target=self._loop,name='PuryF-Gateway',daemon=True)
        self.monitor.start()
        self.hook_worker=threading.Thread(target=self._hook_loop,name='PuryF-Webhooks',daemon=True)
        self.hook_worker.start()

    def account(self,owner):
        if owner not in self.config['_accounts']:fail(401,'unauthorized','Unknown account')
        return self.config['_accounts'][owner]

    def rate(self,owner):
        with self.lock:
            account=self.account(owner)
            used=self.db.execute("SELECT COUNT(*) FROM usage WHERE owner=? AND kind='request' AND stamp>?",(owner,time.time()-60)).fetchone()[0]
            if used>=account['requests_per_minute']:fail(429,'rate_limit','Request rate exceeded; retry later')
            self.db.execute('INSERT INTO usage VALUES (?,?,?,?)',(owner,'request',time.time(),1));self.db.commit()

    def storage(self,owner):
        total=self.db.execute('SELECT COALESCE(SUM(size),0) FROM uploads WHERE owner=?',(owner,)).fetchone()[0]
        for row in self.db.execute('SELECT id FROM jobs WHERE owner=?',(owner,)).fetchall():
            folder=self.root/'work'/row['id']
            total+=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file() and not p.is_symlink())
        return total

    def route(self,path):
        ext=path.suffix.lower()
        if ext not in ALL_EXTS or ext in {'.zip','.url','.dwg','.dxf'}:fail(422,'unsupported_route','Conversion route is not supported')
        if self.config['mode']=='hosted' and ext not in HOSTED_FORMATS:
            fail(422,'unsupported_route','This format is disabled on the hosted server; desktop Office automation is unavailable')
        if (ext in OFFICE_EXTS or ext in {'.msg','.html','.htm','.mht','.mhtml'}) and not self.config.get('allow_office',False):
            fail(422,'office_disabled','Office routes require explicit local administrator opt-in')

    def validate_upload(self,path):
        self.route(path)
        ext=path.suffix.lower()
        try:
            if ext=='.pdf':
                reader=PdfReader(path)
                if not reader.is_encrypted and len(reader.pages)>1000:fail(422,'document_limit','PDF exceeds 1000 pages')
            elif ext in ('.txt','.md'):
                path.read_text(encoding='utf-8-sig')
            else:
                with Image.open(path) as image:
                    if image.width*image.height>40_000_000 or getattr(image,'n_frames',1)>1000:fail(422,'document_limit','Image exceeds pixel/frame limits')
                    image.verify()
        except APIError:raise
        except Exception:fail(422,'invalid_upload','File content does not match a supported readable document')

    def upload(self,owner,name,stream,length):
        if self.config['mode']!='hosted':fail(404,'not_found','Upload endpoint is hosted-only')
        name=filename(name);self.route(Path(name));integer(length,1,self.config['max_file_bytes'],'Content-Length')
        with self.lock:
            account=self.account(owner)
            uploaded=self.db.execute("SELECT COUNT(*) FROM usage WHERE owner=? AND kind='upload' AND stamp>?",(owner,time.time()-86400)).fetchone()[0]
            if uploaded>=account['max_jobs_day']*self.config['max_files']:fail(429,'upload_limit','Daily upload count exceeded')
            if self.storage(owner)+length>account['max_storage_bytes']:fail(429,'storage_limit','Customer storage quota exceeded')
            uid=uuid.uuid4().hex;folder=self.root/'uploads'/uid;folder.mkdir()
            path=folder/name
            try:
                with path.open('xb') as target:
                    remaining=length
                    while remaining:
                        chunk=stream.read(min(65536,remaining))
                        if not chunk:fail(400,'incomplete_upload','Upload ended early')
                        target.write(chunk);remaining-=len(chunk)
                self.validate_upload(path)
                self.db.execute('INSERT INTO uploads VALUES (?,?,?,?,?,?)',(uid,owner,str(path),name,length,time.time()));self.db.commit()
                self.db.execute('INSERT INTO usage VALUES (?,?,?,?)',(owner,'upload',time.time(),1));self.db.commit()
            except Exception:
                shutil.rmtree(folder);raise
            return {'id':uid,'name':name,'size':length,'expires_in':self.config['retention_seconds']}

    def _row(self,owner,jid):
        self.account(owner)
        row=self.db.execute('SELECT * FROM jobs WHERE id=? AND owner=?',(jid,owner)).fetchone()
        if row is None:fail(404,'not_found','Job not found')
        if row['finished'] is not None and row['finished']+self.config['retention_seconds']<=time.time():fail(410,'job_expired','Job retention period has ended')
        return row

    def _paths(self,owner,inputs):
        if not isinstance(inputs,list) or not 1<=len(inputs)<=self.config['max_files'] or any(not isinstance(x,str) or not x for x in inputs):
            fail(400,'invalid_inputs','inputs must be a bounded nonempty list of paths or upload IDs')
        paths=[]
        for value in inputs:
            if self.config['mode']=='hosted':
                row=self.db.execute('SELECT * FROM uploads WHERE id=? AND owner=?',(value,owner)).fetchone()
                if row is None or row['created']+self.config['retention_seconds']<time.time():fail(404,'not_found','Upload not found or expired')
                path=FolderPolicy.check(row['path'])
            else:path=self.config['_policy'].input(value)
            if not path.is_file() or path.stat().st_size>self.config['max_file_bytes']:fail(422,'input_limit','Missing or oversized input')
            self.route(path);paths.append(path)
        return paths

    def submit(self,owner,request,ikey=None):
        object_fields(request,{'operation','inputs','options','pages','every','input_password','output_password','webhook_id'},('operation','inputs'))
        operation=request['operation']
        if operation not in ('convert','merge','split'):fail(400,'invalid_operation','Choose convert, merge or split')
        config=request.get('options',{})
        if not isinstance(config,dict) or set(config)&{'overwrite','output_folder','password_pdf','pdf_password','source_root','preserve_folders'}:
            fail(400,'invalid_options','Output paths, overwrite and raw option passwords are controlled by the gateway')
        password=request.get('output_password','');input_password=request.get('input_password','')
        if any(not isinstance(p,str) or len(p)>256 for p in (password,input_password)):fail(400,'invalid_password','Invalid password value')
        settings=dict(config)
        if password:settings.update(password_pdf=True,pdf_password=password)
        try:options=ConversionOptions.from_mapping(settings)
        except ValueError as error:fail(400,'invalid_options',str(error))
        if operation!='convert' and (options.merge_pdf or options.compress_pdf or options.ocr_pdf):fail(400,'invalid_options','Conversion post-processing is not supported for PDF-tool jobs')
        if operation!='split' and any(key in request for key in ('pages','every')):fail(400,'invalid_request','Page selection is split-only')
        if operation=='convert' and input_password:fail(400,'invalid_request','Source passwords are supported by merge/split')
        if self.config['mode']=='hosted' and options.ocr_pdf:fail(422,'unsupported_route','Hosted OCR is not enabled')
        hook=request.get('webhook_id')
        if hook is not None and (not isinstance(hook,str) or hook not in self.config.get('webhooks',{}) or self.config['webhooks'][hook]['account']!=owner):fail(400,'invalid_webhook','Unknown administrator-configured webhook preset for this account')
        if ikey is not None and (not isinstance(ikey,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}',ikey)):fail(400,'invalid_idempotency_key','Use 8-128 ASCII key characters')
        fingerprint=hmac.new(self.secret,encoded(request),hashlib.sha256).hexdigest()
        with self.lock:
            account=self.account(owner)
            if ikey:
                prior=self.db.execute('SELECT * FROM jobs WHERE owner=? AND ikey=?',(owner,ikey)).fetchone()
                if prior:
                    if prior['request_hash']!=fingerprint:fail(409,'idempotency_conflict','Key was already used for a different request')
                    return self.get(owner,prior['id']),True
            active=self.db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND status NOT IN ('succeeded','partial','failed','skipped','cancelled')",(owner,)).fetchone()[0]
            daily=self.db.execute("SELECT COUNT(*) FROM usage WHERE owner=? AND kind='job' AND stamp>?",(owner,time.time()-86400)).fetchone()[0]
            if active>=account['max_active_jobs'] or daily>=account['max_jobs_day']:fail(429,'job_limit','Customer job quota exceeded')
            if self.storage(owner)>=account['max_storage_bytes']:fail(429,'storage_limit','Customer storage quota exceeded')
            paths=self._paths(owner,request['inputs'])
            if operation in ('merge','split') and any(p.suffix.lower()!='.pdf' for p in paths):fail(422,'invalid_pdf_source','PDF tools require PDF inputs')
            if self.config['mode']=='hosted' and operation in ('merge','split'):
                try:
                    for path in paths:
                        reader=PdfReader(path)
                        if reader.is_encrypted and not reader.decrypt(input_password):fail(422,'invalid_pdf_password','Cannot unlock source PDF')
                        if len(reader.pages)>1000:fail(422,'document_limit','PDF exceeds 1000 pages')
                except APIError:raise
                except Exception:fail(422,'invalid_pdf_source','Cannot read PDF source')
            if operation=='split':
                if len(paths)!=1:fail(400,'invalid_inputs','Split requires one input')
                if 'every' in request:
                    integer(request['every'],1,1000,'every')
                    if 'pages' in request:fail(400,'invalid_request','Choose pages or every')
                elif not isinstance(request.get('pages'),str) or not request['pages'].strip():fail(400,'invalid_request','Split requires pages or every')
            jid=uuid.uuid4().hex;folder=self.root/'work'/jid;out=folder/'outputs';out.mkdir(parents=True)
            options=replace(options,output_folder=str(out),command_timeout=min(options.command_timeout,self.config['job_timeout_seconds']))
            if operation!='convert':options=replace(options,output_folder='')
            # Reserve durable idempotency metadata before handing work to the service.
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)',(jid,owner,None,time.time(),None,'reserved',fingerprint,ikey,json.dumps(request['inputs']),None,hook));self.db.commit()
            try:
                if operation=='convert':handle=self.service.submit_conversion(paths,options,origin='gateway')
                elif operation=='merge':handle=self.service.submit_merge(paths,out/'merged.pdf',options,passwords={str(p):input_password for p in paths},origin='gateway')
                else:handle=self.service.submit_split(paths[0],options,output_dir=out if 'every' in request else None,
                    output_file=out/'selected.pdf' if 'pages' in request else None,every_n=request.get('every'),page_ranges=request.get('pages'),password=input_password,origin='gateway')
                self.db.execute('UPDATE jobs SET core=?,status=? WHERE id=?',(handle.id,'queued',jid))
                self.db.execute('INSERT INTO usage VALUES (?,?,?,?)',(owner,'job',time.time(),1));self.db.commit()
            except Exception:
                self.db.execute('DELETE FROM jobs WHERE id=?',(jid,));self.db.commit();shutil.rmtree(folder);raise
            return self.get(owner,jid),False

    def _snapshot(self,row):
        if row['status'] in TERMINAL and row['snapshot']:
            return json.loads(row['snapshot'])
        if row['core']:
            try:raw=self.service.get_job(row['core'])
            except KeyError:raw=None
            if raw is not None:
                # Public snapshots never expose server paths, report contents or converter logs.
                output_rows=[]
                for n, output in enumerate(raw['outputs']):
                    output_path=Path(output['path'])
                    try:
                        output_size=output_path.stat().st_size if output_path.is_file() else 0
                    except OSError:
                        output_size=0
                    output_rows.append({'index':n,'name':output_path.name,'size':output_size,
                                        'available':output_size > 0})
                result={'id':row['id'],'operation':raw['operation'],'status':raw['status'],'created_at':raw['created_at'],
                    'finished_at':raw['finished_at'],'progress':dict(raw['progress']),'cancel_requested':raw['cancel_requested'],
                    'options':{k:v for k,v in raw['options'].items() if k!='output_folder'},
                    'inputs':[{'index':n,'name':Path(i['source']).name,'status':i['status']} for n,i in enumerate(raw['inputs'])],
                    'outputs':output_rows,
                    'errors':[{'code':e['code'],'message':'Conversion failed; check format requirements or local server diagnostics'} for e in raw['errors']]}
                result['progress']['current']=Path(result['progress'].get('current','')).name
                return result
        return json.loads(row['snapshot']) if row['snapshot'] else {'id':row['id'],'status':row['status'],'outputs':[],'errors':[]}

    def get(self,owner,jid):
        with self.lock:return self._snapshot(self._row(owner,jid))

    def cancel(self,owner,jid):
        with self.lock:
            row=self._row(owner,jid)
            if row['core']:
                try:self.service.cancel(row['core'])
                except KeyError:pass
            return self._snapshot(row)

    def asset(self,owner,jid,index):
        with self.lock:
            row=self._row(owner,jid);snapshot=self._snapshot(row)
            if snapshot['status'] not in TERMINAL:fail(409,'job_not_finished','Wait until the job finishes')
            outputs=snapshot.get('outputs',[])
            if index=='archive':
                if not outputs:fail(404,'not_found','No outputs')
                archive=self.root/'work'/jid/'results.zip'
                if not archive.exists():
                    size=sum(o['size'] for o in outputs)
                    if self.storage(owner)+size>self.account(owner)['max_storage_bytes']:fail(429,'storage_limit','Not enough storage quota to build an archive')
                    temporary=archive.with_suffix('.tmp')
                    try:
                        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_STORED) as target:
                            for output in outputs:target.write(self.asset(owner,jid,output['index']),f"{output['index']+1}_{output['name']}")
                        temporary.replace(archive)
                    finally:temporary.unlink(missing_ok=True)
                return FolderPolicy.check(archive)
            integer(index,0,len(outputs)-1,'asset index')
            # Retrieve actual outputs from the service, or the persisted private manifest.
            manifest=self.root/'work'/jid/'manifest.json'
            if row['core']:
                try:paths=[o['path'] for o in self.service.get_job(row['core'])['outputs']]
                except KeyError:paths=json.loads(manifest.read_text())
            else:paths=json.loads(manifest.read_text())
            path=FolderPolicy.check(paths[index]);root=self.root/'work'/jid/'outputs'
            if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower()!='.pdf':fail(404,'not_found','Output not available')
            return path

    def link(self,owner,jid,asset,ttl):
        integer(ttl,1,3600,'ttl_seconds');self.asset(owner,jid,asset)
        with self.lock:
            row=self._row(owner,jid)
            expiry=min(int(time.time()+ttl),int((row['finished'] or time.time())+self.config['retention_seconds']))
        payload=base64.urlsafe_b64encode(encoded({'owner':owner,'job':jid,'asset':asset,'exp':expiry})).decode().rstrip('=')
        signature=hmac.new(self.secret,payload.encode(),hashlib.sha256).hexdigest()
        return {'path':'/d/'+payload+'.'+signature,'expires_at':expiry}

    def resolve_link(self,token):
        try:
            payload,signature=token.split('.')
            if not hmac.compare_digest(hmac.new(self.secret,payload.encode(),hashlib.sha256).hexdigest(),signature):raise ValueError()
            data=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
            if data['exp']<=time.time():raise ValueError()
            return self.asset(data['owner'],data['job'],data['asset'])
        except (ValueError,KeyError,TypeError):fail(403,'invalid_download_link','Download link is invalid or expired')

    def dependencies(self,owner,inputs):
        with self.lock:paths=self._paths(owner,inputs)
        checks=self.service.check_dependencies(paths)
        return {'ready':all(c['ready'] for c in checks),'inputs':[{'index':n,'ready':c['ready'],'issues':c['issues']} for n,c in enumerate(checks)]}

    def capabilities(self):
        formats=HOSTED_FORMATS if self.config['mode']=='hosted' else ALL_EXTS-{'.zip','.url','.dwg','.dxf'}
        inspector=ConverterEngine(ConversionOptions().engine_settings(),lambda s:None,lambda *a:None,lambda *a:None,threading.Event())
        available=[]
        for ext in sorted(formats):
            try:self.route(Path('sample'+ext));issues=inspector.requirements(Path('sample'+ext))
            except APIError as error:issues=[str(error)]
            available.append({'extension':ext,'ready':not issues,'issues':issues})
        return {'mode':self.config['mode'],'formats':available,'operations':['convert','merge','split'],
            'max_files':self.config['max_files'],'max_file_bytes':self.config['max_file_bytes'],
            'retention_seconds':self.config['retention_seconds'],'hosted_office':False,
            'mcp_streamable_http':False,'progress':'poll GET job status','schema_version':1}

    def _refresh(self):
        for row in self.db.execute('SELECT * FROM jobs WHERE core IS NOT NULL').fetchall():
            try:raw=self.service.get_job(row['core'])
            except KeyError:continue
            if row['status'] in TERMINAL:continue
            if raw['status'] not in TERMINAL and time.time()-row['created']>self.config['job_timeout_seconds']:self.service.cancel(row['core'])
            snapshot=self._snapshot(row);finished=time.time() if raw['status'] in TERMINAL else None
            if finished:
                if self.storage(row['owner'])>self.account(row['owner'])['max_storage_bytes']:
                    # Only owned job outputs may be removed by quota enforcement.
                    shutil.rmtree(self.root/'work'/row['id']/'outputs')
                    (self.root/'work'/row['id']/'outputs').mkdir()
                    snapshot.update(status='failed',outputs=[],errors=[{'code':'storage_limit','message':'Output storage quota exceeded'}])
                paths=[o['path'] for o in raw['outputs']] if snapshot['outputs'] else []
                (self.root/'work'/row['id']/'manifest.json').write_text(json.dumps(paths))
                if row['hook']:
                    body=json.dumps({'event':'job.completed','job':snapshot},sort_keys=True)
                    self.db.execute('INSERT OR IGNORE INTO hooks VALUES (?,?,?,?,?,?,?)',(row['id'],row['owner'],row['hook'],body,0,time.time(),'pending'))
            self.db.execute('UPDATE jobs SET status=?,finished=?,snapshot=? WHERE id=?',(snapshot['status'],finished,json.dumps(snapshot),row['id']))
        self.db.commit()

    def _cleanup(self):
        cutoff=time.time()-self.config['retention_seconds']
        for row in self.db.execute('SELECT * FROM jobs WHERE finished IS NOT NULL AND finished<?',(cutoff,)).fetchall():
            if row['core']:
                try:self.service.forget(row['core'])
                except (KeyError,ValueError):pass
            shutil.rmtree(self.root/'work'/row['id'],ignore_errors=True)
            self.db.execute('DELETE FROM hooks WHERE job=?',(row['id'],));self.db.execute('DELETE FROM jobs WHERE id=?',(row['id'],))
        active_inputs=set()
        for row in self.db.execute("SELECT inputs FROM jobs WHERE status NOT IN ('succeeded','failed','partial','skipped','cancelled')").fetchall():active_inputs.update(json.loads(row['inputs']))
        for row in self.db.execute('SELECT * FROM uploads WHERE created<?',(cutoff,)).fetchall():
            if row['id'] not in active_inputs:
                shutil.rmtree(self.root/'uploads'/row['id'],ignore_errors=True);self.db.execute('DELETE FROM uploads WHERE id=?',(row['id'],))
        self.db.execute('DELETE FROM usage WHERE stamp<?',(time.time()-7*86400,));self.db.commit()
        # A crashed publisher may have left an unregistered upload/job directory.
        for kind,table in [('uploads','uploads'),('work','jobs')]:
            known={r['id'] for r in self.db.execute('SELECT id FROM '+table)}
            for folder in (self.root/kind).iterdir():
                if folder.name not in known and folder.is_dir() and not folder.is_symlink() and folder.stat().st_mtime<cutoff:shutil.rmtree(folder)
        report_root=self.root/'reports'
        if report_root.exists():
            for path in report_root.glob('*.csv'):
                if path.stat().st_mtime<cutoff:path.unlink()

    def _loop(self):
        while not self.stop.wait(.2):
            try:
                with self.lock:self._refresh();self._cleanup()
            except Exception:
                # No tenant document paths or credentials in external diagnostics.
                import sys
                print('PuryF integration maintenance failed; inspect server storage/permissions.',file=sys.stderr)

    def _hook_loop(self):
        while not self.stop.wait(.5):
            try:self.deliver_hooks()
            except Exception:pass

    def deliver_hooks(self):
        from .webhooks import send
        with self.lock:pending=self.db.execute("SELECT * FROM hooks WHERE status='pending' AND next<=? ORDER BY next LIMIT 1",(time.time(),)).fetchall()
        for row in pending:
            with self.lock:
                claimed=self.db.execute("UPDATE hooks SET status='sending' WHERE job=? AND status='pending'",(row['job'],)).rowcount
                self.db.commit()
            if not claimed:continue
            preset=self.config.get('webhooks',{}).get(row['preset'])
            success=False
            if preset:
                try:success=send(preset,row['job'],row['body'].encode())
                except Exception:pass
            if self.stop.is_set():return  # leave claimed delivery for recovery, never touch a closed DB
            attempts=row['attempts']+1;status='delivered' if success else 'failed' if attempts>=5 else 'pending'
            with self.lock:
                self.db.execute('UPDATE hooks SET attempts=?,status=?,next=? WHERE job=?',(attempts,status,time.time()+5*3**(attempts-1),row['job']));self.db.commit()

    def close(self):
        self.stop.set();self.monitor.join();self.hook_worker.join(timeout=6)
        self.service.close()
        with self.lock:self._refresh();self.db.close()
        self.owner.close()
        self.registration.close()
        try:
            self.registration.path.unlink();self.registration.path.parent.rmdir()
        except OSError:pass

# SPDX-License-Identifier: MIT
"""Local presets, history and diagnostic export. No passwords are persisted."""
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import platform
import re
import sqlite3
import tempfile
import threading
import time

QUALITY={'Original':{},'Print':{'image_max_edge':4800},'Balanced':{'image_max_edge':2400},'Small':{'image_max_edge':1400,'compress_pdf':True}}

def content_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()

def safe_basename(name):
    if not name or len(name)>250 or name in ('.','..') or name.endswith((' ','.')) or any(ord(c)<32 or c in '<>:"/\\|?*' for c in name):raise ValueError('Naming rule produced an invalid filename')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[p+str(i) for p in ('COM','LPT') for i in range(1,10)]}:raise ValueError('Reserved filename')
    return name

def duplicates(paths):
    groups={}
    for path in paths:
        path=Path(path)
        if path.is_file():groups.setdefault((path.stat().st_size,content_hash(path)),[]).append(str(path))
    return [values for values in groups.values() if len(values)>1]

class Store:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'history.sqlite3'
        with self.connect() as db:db.executescript('''CREATE TABLE IF NOT EXISTS history(id TEXT PRIMARY KEY,stamp REAL,payload TEXT);
CREATE TABLE IF NOT EXISTS presets(name TEXT PRIMARY KEY,options TEXT);
CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS automation(rule TEXT,path TEXT,digest TEXT,state TEXT,job TEXT,PRIMARY KEY(rule,path));
CREATE TABLE IF NOT EXISTS schedules(name TEXT,bucket INTEGER,PRIMARY KEY(name,bucket));''')
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            yield db
        finally:
            db.close()
    def preset_names(self):
        with self.connect() as db:return sorted(set(QUALITY)|{r[0] for r in db.execute('SELECT name FROM presets')})
    def preset(self,name):
        with self.connect() as db:row=db.execute('SELECT options FROM presets WHERE name=?',(name,)).fetchone()
        if row:return json.loads(row[0])
        if name not in QUALITY:raise ValueError('Unknown preset: '+name)
        return dict(QUALITY[name])
    def save_preset(self,name,options):
        from .options import ConversionOptions
        if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValueError('Invalid preset name')
        normalized=ConversionOptions.from_mapping(options).public_settings()
        normalized.pop('password_supplied',None);normalized.pop('password_pdf',None)
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO presets VALUES (?,?)',(name,json.dumps(normalized)))
    def get(self,key,default=None):
        with self.connect() as db:row=db.execute('SELECT value FROM settings WHERE name=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def set(self,key,value):
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps(value)))
    def record(self,job):
        data=json.loads(json.dumps(job));data['options'].pop('password_supplied',None);data['options'].pop('password_pdf',None)
        data['requires_output_password']=bool(job['options'].get('password_pdf'))
        # Reviewed OCR text and any private PDF passwords are not history parameters.
        data['parameters']={k:v for k,v in data.get('parameters',{}).items() if k not in ('reviewed_text','password','input_password','output_password')}
        data['logs']=[];data['errors']=[{'code':e['code']} for e in data.get('errors',[])]
        for item in data.get('inputs',[]):
            item.pop('message',None);item.pop('error',None)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO history VALUES (?,?,?)',(data['id'],time.time(),json.dumps(data)))
            db.execute('DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY stamp DESC LIMIT 1000)')
        folders=[str(Path(o['path']).parent) for o in data.get('outputs',[])]
        if folders:self.set('recent_output_folders',list(dict.fromkeys(folders+self.get('recent_output_folders',[])))[:10])
    def history(self,limit=100):
        with self.connect() as db:return [json.loads(r[0]) for r in db.execute('SELECT payload FROM history ORDER BY stamp DESC LIMIT ?',(min(limit,1000),))]
    def diagnostic(self):
        from . import __version__
        from .engine import module_available
        jobs=self.history(1000)
        return {'app':'PuryF','version':__version__,'platform':platform.system(),'python':platform.python_version(),
            'modules':{m:module_available(m) for m in ('pypdf','pypdfium2','PIL','reportlab','cryptography','arabic_reshaper','bidi')},
            'job_count':len(jobs),'states':{state:sum(j['status']==state for j in jobs) for state in {'succeeded','failed','partial','cancelled','skipped'}},
            'note':'Paths, filenames, document text, usernames, passwords and raw error/log messages omitted.'}

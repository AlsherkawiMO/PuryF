# SPDX-License-Identifier: MIT
"""Shared folder policy and integration configuration. Not an OS sandbox."""
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets

class APIError(ValueError):
    def __init__(self,status,code,message):
        super().__init__(message);self.status=status;self.code=code

def fail(status,code,message):raise APIError(status,code,message)

def object_fields(value,allowed,required=()):
    if not isinstance(value,dict) or set(value)-set(allowed) or any(k not in value for k in required):
        fail(400,'invalid_request','Invalid or missing request fields')
    return value

def integer(value,low,high,name):
    if type(value) is not int or not low<=value<=high:fail(400,'invalid_request',f'{name} must be an integer between {low} and {high}')
    return value

class FolderPolicy:
    def __init__(self,roots):
        self.roots=[self.check(p,root=True) for p in roots]
        if not self.roots:raise ValueError('Configure at least one permitted input folder')
    @staticmethod
    def check(value,root=False):
        if not isinstance(value,(str,Path)) or not str(value) or '\0' in str(value):fail(403,'path_denied','Invalid path')
        path=Path(value).expanduser()
        if not path.is_absolute():fail(403,'path_denied','Absolute paths are required')
        # Reject symlinks/junctions before resolution, including existing parents.
        for parent in [path,*path.parents]:
            if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):
                fail(403,'path_denied','Linked paths are not permitted')
            try:
                if getattr(parent.lstat(),'st_file_attributes',0)&0x400:
                    fail(403,'path_denied','Windows reparse points are not permitted')
            except FileNotFoundError:pass
            except OSError:fail(403,'path_denied','Path attributes could not be verified')
        path=path.resolve()
        if root and not path.is_dir():raise ValueError('Configured folder must exist')
        return path
    def input(self,value):
        path=self.check(value)
        if not any(path.is_relative_to(root) for root in self.roots):fail(403,'path_denied','Input is outside permitted folders')
        if not path.is_file():fail(400,'missing_input','Input is not a regular file')
        return path

def load_config(file):
    data=json.loads(Path(file).read_text(encoding='utf-8-sig'))
    object_fields(data,{'mode','data_dir','read_roots','accounts','port','allowed_origins','allowed_hosts',
        'allow_office','max_file_mb','max_files','retention_seconds','job_timeout_seconds','webhooks'},('mode','data_dir'))
    if data['mode'] not in ('local','hosted','mcp'):raise ValueError('mode must be local, hosted or mcp')
    root=FolderPolicy.check(data['data_dir']);root.mkdir(parents=True,exist_ok=True)
    data=dict(data);data['data_dir']=root
    data['max_file_bytes']=integer(data.get('max_file_mb',10),1,100,'max_file_mb')*1024*1024
    data['max_files']=integer(data.get('max_files',20),1,100,'max_files')
    data['retention_seconds']=integer(data.get('retention_seconds',86400),60,604800,'retention_seconds')
    data['job_timeout_seconds']=integer(data.get('job_timeout_seconds',900),1,3600,'job_timeout_seconds')
    data['port']=integer(data.get('port',8765),1,65535,'port')
    if type(data.get('allow_office',False)) is not bool:raise ValueError('allow_office must be boolean')
    if data['mode']=='hosted' and data.get('allow_office'):raise ValueError('Hosted Office automation is not supported')
    if data['mode']!='hosted':data['_policy']=FolderPolicy(data.get('read_roots',[]))
    accounts=data.get('accounts',[])
    if not isinstance(accounts,list) or (data['mode']!='mcp' and not accounts):raise ValueError('HTTP accounts are required')
    if data['mode']=='local' and len(accounts)!=1:raise ValueError('Local API supports one local account; use hosted mode for tenants')
    data['_accounts']={}
    fingerprints=set()
    for account in accounts:
        object_fields(account,{'id','token_env','max_jobs_day','max_active_jobs','max_storage_mb','requests_per_minute'},('id','token_env'))
        name=account['id']
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name) or name in data['_accounts']:raise ValueError('Invalid/duplicate account ID')
        if not isinstance(account['token_env'],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',account['token_env']):raise ValueError('Invalid token environment variable name')
        token=os.environ.get(account['token_env'],'')
        if len(token)<32:raise ValueError('Each token environment variable must contain at least 32 characters')
        digest=hashlib.sha256(token.encode()).digest()
        if digest in fingerprints:raise ValueError('Accounts must have different tokens')
        fingerprints.add(digest)
        entry={'digest':digest,'max_jobs_day':integer(account.get('max_jobs_day',100),1,10000,'max_jobs_day'),
            'max_active_jobs':integer(account.get('max_active_jobs',4),1,100,'max_active_jobs'),
            'max_storage_bytes':integer(account.get('max_storage_mb',500),1,100000,'max_storage_mb')*1024*1024,
            'requests_per_minute':integer(account.get('requests_per_minute',120),1,10000,'requests_per_minute')}
        data['_accounts'][name]=entry
    if data['mode']=='mcp':data['_accounts']['mcp']={'max_jobs_day':1000,'max_active_jobs':10,'max_storage_bytes':1024**3,'requests_per_minute':1000}
    for field in ('allowed_origins','allowed_hosts'):
        if not isinstance(data.get(field,[]),list) or any(not isinstance(x,str) or not x or '*' in x for x in data.get(field,[])):raise ValueError(field+' must be an explicit list')
    for origin in data.get('allowed_origins',[]):
        from urllib.parse import urlsplit
        url=urlsplit(origin)
        if url.scheme not in ('http','https') or not url.netloc or url.path or url.query or url.fragment or url.username:raise ValueError('Origin must contain only scheme and authority')
    hooks=data.get('webhooks',{})
    if not isinstance(hooks,dict):raise ValueError('webhooks must be an object')
    from urllib.parse import urlsplit
    for name,hook in hooks.items():
        object_fields(hook,{'url','secret_env','account'},('url','secret_env','account'))
        if hook['account'] not in data['_accounts']:raise ValueError('Webhook must belong to a configured account')
        if not isinstance(hook['url'],str) or not isinstance(hook['secret_env'],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',hook['secret_env']):raise ValueError('Invalid webhook configuration')
        url=urlsplit(hook['url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:raise ValueError('Webhook presets require HTTPS URLs without credentials')
        if len(os.environ.get(hook['secret_env'],''))<32:raise ValueError('Webhook signing secret must contain at least 32 characters')
    return data

def authenticate(config,header):
    if not isinstance(header,str) or not header.startswith('Bearer '):fail(401,'unauthorized','Bearer token required')
    digest=hashlib.sha256(header[7:].encode()).digest()
    for name,account in config['_accounts'].items():
        if hmac.compare_digest(digest,account.get('digest',b'')):return name
    fail(401,'unauthorized','Invalid access token')

# SPDX-License-Identifier: MIT
"""Backend/local automation example. Reads a customer key from the environment."""
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote
from urllib.request import Request,urlopen
import uuid

base=os.environ.get('PURYF_API_BASE','http://127.0.0.1:8765').rstrip('/')
token=os.environ['PURYF_CUSTOMER_TOKEN']

def call(path,method='GET',body=None,headers=None):
    request=Request(base+path,data=body,method=method,headers={'Authorization':'Bearer '+token,**(headers or {})})
    with urlopen(request,timeout=30) as response:return response.read()

def convert(files,output_directory):
    ids=[]
    for value in files:
        file=Path(value)
        # Suitable for the default 10 MiB limit; use a streaming HTTP client for larger configured uploads.
        uploaded=json.loads(call('/v1/uploads?name='+quote(file.name),method='POST',body=file.read_bytes()))
        ids.append(uploaded['id'])
    request=json.dumps({'operation':'convert','inputs':ids}).encode()
    submitted=json.loads(call('/v1/jobs','POST',request,{'Content-Type':'application/json','Idempotency-Key':str(uuid.uuid4())}))
    jid=submitted['job']['id']
    try:
        while True:
            job=json.loads(call('/v1/jobs/'+jid));print(job['status'],job.get('progress',{}))
            if job['status'] in ('succeeded','partial','failed','cancelled','skipped'):break
            time.sleep(1)
    except KeyboardInterrupt:
        call('/v1/jobs/'+jid+'/cancel','POST',b'{}',{'Content-Type':'application/json'});raise
    if job['outputs']:
        folder=Path(output_directory);folder.mkdir(parents=True,exist_ok=True)
        target=folder/('PuryF-'+jid+'.zip')
        with target.open('xb') as stream:stream.write(call('/v1/jobs/'+jid+'/archive'))
        print(target)
    return job

if __name__=='__main__':
    if len(sys.argv)<3:raise SystemExit('Usage: python python_client.py OUTPUT_DIRECTORY FILE [FILE...]')
    result=convert(sys.argv[2:],sys.argv[1]);raise SystemExit(0 if result['status']=='succeeded' else 1)

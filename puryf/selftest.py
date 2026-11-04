# SPDX-License-Identifier: MIT
"""Bundled core check; does not invoke Python or optional external converters."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import threading

def run(clean_pc=False,output=None):
    from reportlab.pdfgen.canvas import Canvas
    from . import __version__
    from .sdk import Client
    from .documents import render,inspect
    from .access import load_config
    from .gateway import Gateway
    from .http_server import Server
    from .mcp_server import Protocol
    if clean_pc and (sys.platform!='win32' or not getattr(sys,'frozen',False)):raise ValueError('--clean-pc must run from the native Windows bundle on a clean Windows machine')
    with tempfile.TemporaryDirectory(prefix='PuryF-selftest-') as folder:
        root=Path(folder);source=root/'notes.txt';source.write_text('PuryF bundled conversion test\nمرحبا بالتدريب',encoding='utf-8')
        with Client(root/'state') as client:
            job=client.convert([source],{'output_folder':str(root/'out')}).wait(20)
            if job['status']!='succeeded':raise RuntimeError('Bundled conversion failed')
            pdf=Path(job['outputs'][0]['path']);image=render(pdf,0,width=160)
            if not image.width or inspect(pdf)['pages']!=1:raise RuntimeError('Bundled preview failed')
            document=client.document([pdf],{'action':'export','output_dir':str(root/'images'),'format':'png'}).wait(20)
            if document['status']!='succeeded':raise RuntimeError('Bundled image export failed')
        old_localappdata=os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA']=str(root/'localappdata')
        try:
            config_file=root/'mcp.json';config_file.write_text(json.dumps({'mode':'mcp','data_dir':str(root/'mcp'),'read_roots':[str(root/'out')]}))
            gateway=Gateway(load_config(config_file))
            try:
                protocol=Protocol(gateway);reply=protocol.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}})
                if 'result' not in reply:raise RuntimeError('Bundled MCP initialization failed')
            finally:gateway.close()
            # Also validate the optional HTTP adapter with a fresh random key, only on loopback.
            import secrets
            name='PURYF_SELFTEST_TOKEN';old=os.environ.get(name);os.environ[name]=secrets.token_urlsafe(32)
            cfg=root/'http.json';cfg.write_text(json.dumps({'mode':'local','data_dir':str(root/'http'),'read_roots':[str(root/'out')],'accounts':[{'id':'test','token_env':name}]}))
            gateway=Gateway(load_config(cfg));server=Server(('127.0.0.1',0),gateway);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                connection=http.client.HTTPConnection(*server.server_address,timeout=5);connection.request('GET','/v1/capabilities',headers={'Authorization':'Bearer '+os.environ[name]})
                response=connection.getresponse();response.read()
                if response.status!=200:raise RuntimeError('Bundled local HTTP authentication failed')
                connection.close()
            finally:
                server.shutdown();server.server_close();thread.join();gateway.close()
                if old is None:os.environ.pop(name,None)
                else:os.environ[name]=old
        finally:
            if old_localappdata is None:os.environ.pop('LOCALAPPDATA',None)
            else:os.environ['LOCALAPPDATA']=old_localappdata
    value={'version':__version__,'platform':platform.system(),'frozen':bool(getattr(sys,'frozen',False)),'core_passed':True,
        'clean_pc_confirmed':bool(clean_pc),'checks':['text conversion','PDF rendering','image export','MCP initialization','authenticated local API'],
        'external_converters':'not tested; Office/OCR/media tools remain separate installations'}
    if getattr(sys,'frozen',False):value['executable_sha256']=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    if output:
        target=Path(output)
        with target.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)
    return value

# SPDX-License-Identifier: MIT
"""Loopback JSON API; use an authenticated TLS reverse proxy for hosted preview."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import re
import socket
import threading
from urllib.parse import parse_qs,urlsplit,unquote

from .access import APIError,authenticate,fail,load_config,object_fields
from .gateway import Gateway

class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=32
    def __init__(self,address,gateway):
        self.gateway=gateway;self.slots=threading.BoundedSemaphore(32)
        super().__init__(address,Handler)
    def process_request(self,request,address):
        if not self.slots.acquire(False):
            try:request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except Exception:self.slots.release();raise
    def process_request_thread(self,*args):
        try:super().process_request_thread(*args)
        finally:self.slots.release()

class Handler(BaseHTTPRequestHandler):
    server_version='PuryF';sys_version=''
    def setup(self):super().setup();self.connection.settimeout(20)
    def log_message(self,*args):pass  # never log tokens, signed links or uploaded names
    def common_headers(self):
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        origin=self.headers.get('Origin')
        if origin and origin in self.server.gateway.config.get('allowed_origins',[]):
            self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
    def json(self,status,value):
        raw=json.dumps(value,ensure_ascii=True).encode()
        self.send_response(status);self.common_headers();self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)))
        if status==401:self.send_header('WWW-Authenticate','Bearer')
        if status==429:self.send_header('Retry-After','60')
        self.end_headers();self.wfile.write(raw)
    def checks(self):
        config=self.server.gateway.config
        port=self.server.server_address[1]
        allowed={f'127.0.0.1:{port}',f'localhost:{port}',*config.get('allowed_hosts',[])}
        if len(self.headers.get_all('Host',[]))!=1 or self.headers.get('Host','').lower() not in {h.lower() for h in allowed}:fail(403,'host_denied','Host is not permitted')
        origin=self.headers.get('Origin')
        if origin is not None and origin not in config.get('allowed_origins',[]):fail(403,'origin_denied','Origin is not permitted')
        if self.headers.get('Transfer-Encoding') is not None:fail(400,'invalid_framing','Chunked requests are not accepted')
    def length(self,maximum):
        values=self.headers.get_all('Content-Length',[])
        if len(values)!=1 or not re.fullmatch(r'[0-9]{1,12}',values[0]):fail(411,'length_required','One Content-Length is required')
        size=int(values[0])
        if size>maximum:fail(413,'body_limit','Request body is too large')
        return size
    def body(self):
        if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':fail(415,'content_type','Use application/json')
        length=self.length(128*1024);raw=self.rfile.read(length)
        if len(raw)!=length:fail(400,'incomplete_body','Request body ended early')
        try:return json.loads(raw)
        except (ValueError,UnicodeError):fail(400,'invalid_json','Invalid JSON request')
    def download(self,path):
        with path.open('rb') as source:
            size=path.stat().st_size
            self.send_response(200);self.common_headers()
            self.send_header('Content-Type','application/zip' if path.suffix=='.zip' else 'application/pdf')
            self.send_header('Content-Disposition','attachment; filename="'+('results.zip' if path.suffix=='.zip' else 'result.pdf')+'"')
            self.send_header('Content-Length',str(size));self.end_headers()
            while chunk:=source.read(65536):self.wfile.write(chunk)
    def handle_route(self,method):
        self.close_connection=True
        try:
            self.checks();gateway=self.server.gateway
            parsed=urlsplit(self.path);path=parsed.path
            if method=='OPTIONS':
                self.send_response(204);self.common_headers()
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type, Idempotency-Key')
                self.send_header('Content-Length','0');self.end_headers();return
            if method=='GET' and path.startswith('/d/'):
                if len(path)>2048:fail(403,'invalid_download_link','Invalid link')
                self.download(gateway.resolve_link(path[3:]));return
            if parsed.query and path!='/v1/uploads':fail(400,'invalid_query','Query parameters are not accepted')
            owner=authenticate(gateway.config,self.headers.get('Authorization'))
            gateway.rate(owner)
            if method=='GET' and path=='/v1/capabilities':self.json(200,gateway.capabilities());return
            if method=='POST' and path=='/v1/uploads':
                query=parse_qs(parsed.query,strict_parsing=True)
                if set(query)!={'name'} or len(query['name'])!=1:fail(400,'invalid_filename','Use ?name=filename')
                size=self.length(gateway.config['max_file_bytes'])
                self.json(201,gateway.upload(owner,query['name'][0],self.rfile,size));return
            if method=='POST' and path=='/v1/jobs':
                result,replay=gateway.submit(owner,self.body(),self.headers.get('Idempotency-Key'))
                self.json(200 if replay else 202,{'job':result,'replayed':replay});return
            if method=='POST' and path=='/v1/dependencies':
                body=object_fields(self.body(),{'inputs'},('inputs',))
                self.json(200,gateway.dependencies(owner,body['inputs']));return
            match=re.fullmatch(r'/v1/jobs/([a-f0-9]{32})(?:/(cancel|results|archive|links|files/[0-9]+))?',path)
            if match:
                jid,action=match.groups()
                if method=='GET' and action in (None,'results'):
                    self.json(200,gateway.get(owner,jid));return
                if method=='POST' and action=='cancel':
                    object_fields(self.body(),{})
                    self.json(200,gateway.cancel(owner,jid));return
                if method=='POST' and action=='links':
                    body=object_fields(self.body(),{'asset','ttl_seconds'},('asset',))
                    self.json(201,gateway.link(owner,jid,body['asset'],body.get('ttl_seconds',300)));return
                if method=='GET' and (action=='archive' or action and action.startswith('files/')):
                    asset='archive' if action=='archive' else int(action.split('/')[1])
                    self.download(gateway.asset(owner,jid,asset));return
            fail(404,'not_found','Endpoint not found')
        except APIError as error:self.json(error.status,{'error':{'code':error.code,'message':str(error)}})
        except (ValueError,TypeError,KeyError):self.json(400,{'error':{'code':'invalid_request','message':'Malformed request'}})
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
        except FileNotFoundError:self.json(410,{'error':{'code':'file_expired','message':'File is no longer available'}})
        except Exception:self.json(500,{'error':{'code':'internal_error','message':'Internal server error'}})
    def do_GET(self):self.handle_route('GET')
    def do_POST(self):self.handle_route('POST')
    def do_OPTIONS(self):self.handle_route('OPTIONS')

def run(config_file):
    config=load_config(config_file)
    if config['mode']=='mcp':raise ValueError('HTTP requires local or hosted mode')
    gateway=Gateway(config)
    try:
        server=Server(('127.0.0.1',config['port']),gateway)
        import sys
        print(f"PuryF {config['mode']} API listening on 127.0.0.1:{config['port']}",file=sys.stderr)
        try:server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:pass
        finally:server.server_close()
    finally:gateway.close()

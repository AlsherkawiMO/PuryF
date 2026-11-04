"""Real local HTTP/uploads/PDFs, stdio process protocol, isolation and retention."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import http.client
import importlib.abc
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch,Mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from puryf.access import APIError,FolderPolicy,authenticate,load_config
from puryf.gateway import Gateway
from puryf.http_server import Server
from puryf.mcp_server import Protocol,MODERN
from puryf import engine
from pypdf import PdfReader,PdfWriter

TOKEN_A='a'*48;TOKEN_B='b'*48

class GatewayTests(unittest.TestCase):
    def setUp(self):
        import gc;gc.collect()
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.inputs=self.root/'inputs';self.inputs.mkdir()
        self.environment=patch.dict(os.environ,TEST_API_A=TOKEN_A,TEST_API_B=TOKEN_B,TEST_HOOK='h'*48)
        self.environment.start();self.hosts=[];self.servers=[]
    def tearDown(self):
        for server,thread in self.servers:server.shutdown();server.server_close();thread.join()
        for gateway in reversed(self.hosts):gateway.close()
        self.environment.stop();self.tmp.cleanup()
    def config(self,mode='hosted',**extra):
        data={'mode':mode,'data_dir':str(self.root/('data'+str(len(self.hosts)))),
              'read_roots':[str(self.inputs)],'accounts':[{'id':'a','token_env':'TEST_API_A'}],**extra}
        if mode=='hosted':data['accounts'].append({'id':'b','token_env':'TEST_API_B'})
        file=self.root/'config.json';file.write_text(json.dumps(data));return load_config(file)
    def gateway(self,mode='hosted',**extra):
        result=Gateway(self.config(mode,**extra));self.hosts.append(result);return result
    def upload(self,gateway,name='notes.txt',raw=b'PuryF hosted upload'):
        return gateway.upload('a',name,io.BytesIO(raw),len(raw))['id']
    def wait(self,gateway,jid):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            value=gateway.get('a',jid)
            if value['status'] in ('succeeded','partial','failed','skipped','cancelled'):
                with gateway.lock:gateway._refresh()
                return gateway.get('a',jid)
            time.sleep(.01)
        self.fail('Job did not finish')
    def text(self,name='notes.txt'):
        path=self.inputs/name;path.write_text('Local PDF conversion');return path
    def pdf(self,pages=4):
        writer=PdfWriter()
        for i in range(pages):writer.add_blank_page(width=200+i,height=300)
        stream=io.BytesIO();writer.write(stream);return stream.getvalue()
    def test_upload_convert_result_zip_and_temporary_links(self):
        gateway=self.gateway();uid=self.upload(gateway)
        job,replay=gateway.submit('a',{'operation':'convert','inputs':[uid]},'first-job-123')
        self.assertFalse(replay);result=self.wait(gateway,job['id']);self.assertEqual(result['status'],'succeeded')
        path=gateway.asset('a',job['id'],0);self.assertEqual(len(PdfReader(path).pages),1)
        archive=gateway.asset('a',job['id'],'archive')
        with zipfile.ZipFile(archive) as zipped:self.assertEqual(len(zipped.namelist()),1)
        grant=gateway.link('a',job['id'],0,10)
        token=grant['path'][3:];self.assertEqual(gateway.resolve_link(token),path)
        with patch('puryf.gateway.time.time',return_value=grant['expires_at']+1):
            with self.assertRaises(APIError):gateway.resolve_link(token)
        with self.assertRaises(APIError):gateway.resolve_link(token[:-1]+'x')
        public=json.dumps(result)
        self.assertNotIn(str(self.root),public);self.assertNotIn('report',result);self.assertNotIn('logs',result)
    def test_tenant_isolation_including_uploads_status_cancel_downloads_links(self):
        gateway=self.gateway();uid=self.upload(gateway)
        with self.assertRaises(APIError):gateway.submit('b',{'operation':'convert','inputs':[uid]})
        job,_=gateway.submit('a',{'operation':'convert','inputs':[uid]});self.wait(gateway,job['id'])
        for action in [lambda:gateway.get('b',job['id']),lambda:gateway.cancel('b',job['id']),
                       lambda:gateway.asset('b',job['id'],0),lambda:gateway.link('b',job['id'],0,5)]:
            with self.assertRaises(APIError) as issue:action()
            self.assertEqual(issue.exception.status,404)
    def test_idempotency_atomic_replay_conflict_and_daily_usage(self):
        gateway=self.gateway();uid=self.upload(gateway);request={'operation':'convert','inputs':[uid]}
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses=list(pool.map(lambda _:gateway.submit('a',request,'bulk-request-001'),range(8)))
        self.assertEqual(len({r[0]['id'] for r in responses}),1)
        self.assertEqual(sum(not r[1] for r in responses),1)
        with self.assertRaises(APIError) as issue:gateway.submit('a',{**request,'options':{'compress_pdf':True}},'bulk-request-001')
        self.assertEqual(issue.exception.status,409)
        self.wait(gateway,responses[0][0]['id'])
        gateway.config['_accounts']['a']['max_jobs_day']=1
        with self.assertRaises(APIError) as issue:gateway.submit('a',request,'another-request')
        self.assertEqual(issue.exception.status,429)
    def test_hosted_rejects_paths_office_scripts_and_false_document_content(self):
        gateway=self.gateway()
        for name,raw in [('office.docx',b'test'),('cat.png',b'not an image'),('../escape.txt',b'text'),('CON.txt',b'text'),('script.html',b'<script>')]:
            with self.assertRaises(APIError):self.upload(gateway,name,raw)
        with self.assertRaises(APIError):gateway.submit('a',{'operation':'convert','inputs':[str(self.text())]})
        self.assertEqual(list((gateway.root/'uploads').iterdir()),[])
    def test_folder_policy_denies_outside_traversal_and_symlinks(self):
        gateway=self.gateway('local');source=self.text()
        job,_=gateway.submit('a',{'operation':'convert','inputs':[str(source)]});self.assertEqual(self.wait(gateway,job['id'])['status'],'succeeded')
        outside=self.root/'outside.txt';outside.write_text('private')
        for path in [str(outside),str(self.inputs/'../outside.txt'),'notes.txt']:
            with self.assertRaises(APIError):gateway.submit('a',{'operation':'convert','inputs':[path]})
        try:(self.inputs/'linked.txt').symlink_to(outside)
        except OSError:return
        with self.assertRaises(APIError):gateway.submit('a',{'operation':'convert','inputs':[str(self.inputs/'linked.txt')]})
    def test_invalid_options_source_passwords_and_split_modes(self):
        gateway=self.gateway();uid=self.upload(gateway)
        requests=[{'operation':'convert','inputs':[uid],'options':{'output_folder':str(self.root)}},
                  {'operation':'convert','inputs':[uid],'options':{'overwrite':True}},
                  {'operation':'convert','inputs':[uid],'options':{'pdf_password':'secret'}},
                  {'operation':'convert','inputs':[uid],'pages':'1'},
                  {'operation':'split','inputs':[uid],'every':0},
                  {'operation':'convert','inputs':[]}, {'operation':'shell','inputs':[uid]}]
        for request in requests:
            with self.assertRaises(APIError):gateway.submit('a',request)
        self.assertEqual(gateway.service.list_jobs(),[])
    def test_hosted_merge_split_and_output_password_redaction(self):
        gateway=self.gateway();uid=self.upload(gateway,'source.pdf',self.pdf())
        split,_=gateway.submit('a',{'operation':'split','inputs':[uid],'every':2,'output_password':'private-test-password'})
        result=self.wait(gateway,split['id']);self.assertEqual(result['status'],'succeeded');self.assertEqual(len(result['outputs']),2)
        self.assertNotIn('private-test-password',json.dumps(result))
        reader=PdfReader(gateway.asset('a',split['id'],0));self.assertTrue(reader.decrypt('private-test-password'))
        merged,_=gateway.submit('a',{'operation':'merge','inputs':[uid,uid]})
        self.wait(gateway,merged['id']);self.assertEqual(len(PdfReader(gateway.asset('a',merged['id'],0)).pages),8)
    def test_upload_limits_and_storage_quota(self):
        gateway=self.gateway();gateway.config['max_file_bytes']=2
        with self.assertRaises(APIError):self.upload(gateway,raw=b'long')
        gateway.config['max_file_bytes']=100;gateway.config['_accounts']['a']['max_storage_bytes']=2
        with self.assertRaises(APIError):self.upload(gateway,raw=b'long')
        with self.assertRaises(APIError):gateway.upload('a','x.txt',io.BytesIO(b'x'),2)
        self.assertEqual(list((gateway.root/'uploads').iterdir()),[])
    def test_cancellation_no_new_commit_and_deadline(self):
        gateway=self.gateway();uid=self.upload(gateway);entered=threading.Event();release=threading.Event()
        original=engine.ConverterEngine.convert
        def blocked(converter,path):entered.set();release.wait(5);return original(converter,path)
        with patch.object(engine.ConverterEngine,'convert',blocked):
            job,_=gateway.submit('a',{'operation':'convert','inputs':[uid]})
            self.assertTrue(entered.wait(2));gateway.cancel('a',job['id']);release.set()
            result=self.wait(gateway,job['id']);self.assertEqual(result['status'],'cancelled');self.assertFalse(result['outputs'])
    def test_cleanup_preserves_active_inputs_and_removes_expired_results(self):
        gateway=self.gateway();uid=self.upload(gateway)
        job,_=gateway.submit('a',{'operation':'convert','inputs':[uid]});self.wait(gateway,job['id'])
        outside=self.text();cut=time.time()-gateway.config['retention_seconds']-1
        with gateway.lock:
            core=gateway._row('a',job['id'])['core']
            gateway.db.execute('UPDATE jobs SET finished=?',(cut,));gateway.db.execute('UPDATE uploads SET created=?',(cut,));gateway.db.commit()
            gateway._cleanup()
        with self.assertRaises(APIError):gateway.get('a',job['id'])
        with self.assertRaises(KeyError):gateway.service.get_job(core)
        self.assertFalse(list((gateway.root/'uploads').iterdir()));self.assertFalse(list((gateway.root/'work').iterdir()))
        self.assertTrue(outside.exists())
    def test_restart_keeps_completed_results_and_idempotency(self):
        config=self.config();gateway=Gateway(config)
        try:
            uid=self.upload(gateway);request={'operation':'convert','inputs':[uid]}
            job,_=gateway.submit('a',request,'persistent-001');self.wait(gateway,job['id'])
        finally:gateway.close()
        reopened=Gateway(config);self.hosts.append(reopened)
        self.assertEqual(reopened.get('a',job['id'])['status'],'succeeded')
        self.assertEqual(len(PdfReader(reopened.asset('a',job['id'],0)).pages),1)
        replay,found=reopened.submit('a',request,'persistent-001');self.assertTrue(found);self.assertEqual(replay['id'],job['id'])
    def test_maintenance_durable_webhook_retries_and_account_scoping(self):
        hooks={'partner':{'url':'https://hooks.example.com/finished','secret_env':'TEST_HOOK','account':'a'}}
        with patch('puryf.webhooks.send',return_value=False) as send:
            gateway=self.gateway(webhooks=hooks);uid=self.upload(gateway)
            with self.assertRaises(APIError):gateway.submit('b',{'operation':'convert','inputs':['wrong'],'webhook_id':'partner'})
            job,_=gateway.submit('a',{'operation':'convert','inputs':[uid],'webhook_id':'partner'});self.wait(gateway,job['id'])
            with gateway.lock:
                gateway.db.execute('UPDATE hooks SET next=0');gateway.db.commit()
            gateway.deliver_hooks()
            self.assertGreaterEqual(send.call_count,1)
            with gateway.lock:
                row=gateway.db.execute('SELECT * FROM hooks').fetchone();self.assertEqual(row['status'],'pending')
            send.return_value=True
            with gateway.lock:gateway.db.execute('UPDATE hooks SET next=0');gateway.db.commit()
            gateway.deliver_hooks()
            with gateway.lock:self.assertEqual(gateway.db.execute('SELECT status FROM hooks').fetchone()[0],'delivered')
    def test_webhook_signature_and_no_redirect_policy(self):
        from puryf import webhooks
        response=Mock();response.status=204;response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.object(webhooks,'build_opener',return_value=opener),patch.object(webhooks.time,'time',return_value=1234):
            self.assertTrue(webhooks.send({'url':'https://hooks.example.com','secret_env':'TEST_HOOK'},'delivery-1',b'{}'))
        request=opener.open.call_args.args[0]
        expected=hmac.new(('h'*48).encode(),b'1234.{}',hashlib.sha256).hexdigest()
        self.assertEqual(request.get_header('X-puryf-signature'),'sha256='+expected)
        self.assertIsNone(webhooks.NoRedirect().redirect_request(None,None,None,None,None,None))
    def test_gateway_refuses_shared_data_directory_owner(self):
        config=self.config();gateway=Gateway(config);self.hosts.append(gateway)
        with self.assertRaises(RuntimeError):Gateway(config)
    def start_http(self,mode='hosted',**extra):
        gateway=self.gateway(mode,**extra);server=Server(('127.0.0.1',0),gateway)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.servers.append((server,thread));return gateway,server
    def request(self,server,method,path,body=None,token=TOKEN_A,**headers):
        connection=http.client.HTTPConnection(*server.server_address,timeout=5)
        if isinstance(body,dict):body=json.dumps(body).encode();headers.setdefault('Content-Type','application/json')
        if token is not None:headers['Authorization']='Bearer '+token
        connection.request(method,path,body=body,headers=headers)
        response=connection.getresponse();raw=response.read();status=response.status;received=dict(response.getheaders());connection.close()
        try:data=json.loads(raw)
        except (ValueError,UnicodeError):data=raw
        return status,data,received
    def test_real_http_auth_origins_host_and_no_cors_wildcard(self):
        gateway,server=self.start_http(allowed_origins=['http://localhost:3000'])
        self.assertEqual(self.request(server,'GET','/v1/capabilities',token=None)[0],401)
        self.assertEqual(self.request(server,'GET','/v1/capabilities',token='wrong')[0],401)
        self.assertEqual(self.request(server,'GET','/v1/capabilities',Origin='https://evil.example')[0],403)
        self.assertEqual(self.request(server,'GET','/v1/capabilities',Host='attacker.example')[0],403)
        status,data,headers=self.request(server,'GET','/v1/capabilities',Origin='http://localhost:3000')
        self.assertEqual(status,200);self.assertEqual(headers['Access-Control-Allow-Origin'],'http://localhost:3000')
        self.assertEqual(self.request(server,'OPTIONS','/v1/jobs',token=None,Origin='http://localhost:3000')[0],204)
    def test_real_http_bulk_upload_job_download_zip_link_and_cancel(self):
        gateway,server=self.start_http();uids=[]
        for name in ('one.txt','two.txt'):
            status,data,_=self.request(server,'POST','/v1/uploads?name='+name,b'HTTP upload')
            self.assertEqual(status,201);uids.append(data['id'])
        status,data,_=self.request(server,'POST','/v1/jobs',{'operation':'convert','inputs':uids},**{'Idempotency-Key':'http-bulk-001'})
        self.assertEqual(status,202);jid=data['job']['id'];self.wait(gateway,jid)
        status,data,_=self.request(server,'GET',f'/v1/jobs/{jid}/results');self.assertEqual(status,200);self.assertEqual(len(data['outputs']),2)
        self.assertEqual(self.request(server,'GET',f'/v1/jobs/{jid}',token=TOKEN_B)[0],404)
        status,raw,_=self.request(server,'GET',f'/v1/jobs/{jid}/files/0');self.assertEqual(status,200);self.assertTrue(raw.startswith(b'%PDF'))
        status,raw,_=self.request(server,'GET',f'/v1/jobs/{jid}/archive');self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(raw)) as zipped:self.assertEqual(len(zipped.namelist()),2)
        status,data,_=self.request(server,'POST',f'/v1/jobs/{jid}/links',{'asset':0,'ttl_seconds':30});self.assertEqual(status,201)
        self.assertEqual(self.request(server,'GET',data['path'],token=None)[0],200)
        status,replay,_=self.request(server,'POST','/v1/jobs',{'operation':'convert','inputs':uids},**{'Idempotency-Key':'http-bulk-001'})
        self.assertEqual(status,200);self.assertTrue(replay['replayed'])
        self.assertEqual(self.request(server,'POST',f'/v1/jobs/{jid}/cancel',{})[0],200)
    def test_real_http_limits_and_unknown_routes(self):
        gateway,server=self.start_http();gateway.config['_accounts']['a']['requests_per_minute']=1
        self.assertEqual(self.request(server,'GET','/v1/capabilities')[0],200)
        self.assertEqual(self.request(server,'GET','/v1/capabilities')[0],429)
        gateway.config['_accounts']['a']['requests_per_minute']=100
        self.assertEqual(self.request(server,'GET','/v1/jobs?token=not-accepted')[0],400)
        self.assertEqual(self.request(server,'POST','/v1/jobs',b'{',**{'Content-Type':'application/json'})[0],400)
        self.assertEqual(self.request(server,'POST','/v1/jobs',b'{}')[0],415)
        self.assertEqual(self.request(server,'POST','/unknown',{})[0],404)
    def test_mcp_modern_and_legacy_tools_permitted_paths(self):
        gateway=self.gateway('mcp',accounts=[]);protocol=Protocol(gateway)
        modern=lambda method,params={}:protocol.handle({'jsonrpc':'2.0','id':1,'method':method,'params':{'_meta':{'io.modelcontextprotocol/protocolVersion':MODERN},**params}})
        self.assertIn('supportedVersions',modern('server/discover')['result'])
        self.assertEqual(len(modern('tools/list')['result']['tools']),8)
        source=self.text()
        value=modern('tools/call',{'name':'puryf_convert','arguments':{'inputs':[str(source)]}})['result']
        self.assertFalse(value['isError']);jid=value['structuredContent']['id']
        deadline=time.monotonic()+5
        while gateway.get('mcp',jid)['status'] not in ('succeeded','failed') and time.monotonic()<deadline:time.sleep(.01)
        status=modern('tools/call',{'name':'puryf_job_status','arguments':{'job_id':jid}})['result']['structuredContent']
        self.assertEqual(status['status'],'succeeded')
        result=modern('tools/call',{'name':'puryf_results','arguments':{'job_id':jid}})['result']['structuredContent']
        self.assertTrue(Path(result['outputs'][0]['path']).is_file())
        denied=modern('tools/call',{'name':'puryf_convert','arguments':{'inputs':[str(self.root/'outside.txt')]}})
        self.assertTrue(denied['result']['isError'])
        legacy=Protocol(gateway)
        self.assertIn('error',legacy.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'}))
        initial=legacy.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}})
        self.assertEqual(initial['result']['protocolVersion'],'2025-11-25')
        self.assertIsNone(legacy.handle({'jsonrpc':'2.0','method':'notifications/initialized'}))
        self.assertIn('tools',legacy.handle({'jsonrpc':'2.0','id':2,'method':'tools/list'})['result'])
    def test_real_stdio_mcp_process_framing_and_shutdown(self):
        config={'mode':'mcp','data_dir':str(self.root/'stdio'),'read_roots':[str(self.inputs)]}
        file=self.root/'stdio.json';file.write_text(json.dumps(config))
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'puryf_capabilities','arguments':{}}}]
        result=subprocess.run([sys.executable,'-m','puryf','mcp','--config',str(file)],cwd=ROOT,
            input='\n'.join(json.dumps(x) for x in messages)+'\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        replies=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([reply['id'] for reply in replies],[1,2,3]);self.assertFalse(replies[-1]['result']['isError'])
    def test_config_invalid_tokens_and_hosted_office_opt_in_are_refused(self):
        with self.assertRaises(ValueError):self.config('hosted',allow_office=True)
        with patch.dict(os.environ,TEST_API_A='short'):
            with self.assertRaises(ValueError):self.config('local')
        with self.assertRaises(ValueError):self.config('local',allowed_origins=['*'])

    def test_cleanup_keeps_an_active_jobs_expired_upload_until_terminal(self):
        gateway=self.gateway();uid=self.upload(gateway);entered=threading.Event();release=threading.Event()
        original=engine.ConverterEngine.convert
        def blocked(converter,path):entered.set();release.wait(5);return original(converter,path)
        with patch.object(engine.ConverterEngine,'convert',blocked):
            job,_=gateway.submit('a',{'operation':'convert','inputs':[uid]});self.assertTrue(entered.wait(2))
            with gateway.lock:
                gateway.db.execute('UPDATE uploads SET created=?',(time.time()-gateway.config['retention_seconds']-1,));gateway.db.commit()
                gateway._cleanup()
                self.assertIsNotNone(gateway.db.execute('SELECT id FROM uploads WHERE id=?',(uid,)).fetchone())
            release.set();self.assertEqual(self.wait(gateway,job['id'])['status'],'succeeded')
        with gateway.lock:gateway._cleanup();self.assertEqual(gateway.db.execute('SELECT COUNT(*) FROM uploads').fetchone()[0],0)

    def test_output_quota_failure_is_persisted_and_cannot_download(self):
        gateway=self.gateway();uid=self.upload(gateway)
        job,_=gateway.submit('a',{'operation':'convert','inputs':[uid]})
        gateway.service.wait(gateway._row('a',job['id'])['core'],5)
        gateway.config['_accounts']['a']['max_storage_bytes']=1
        with gateway.lock:gateway._refresh()
        result=gateway.get('a',job['id'])
        self.assertEqual(result['status'],'failed');self.assertFalse(result['outputs'])
        self.assertEqual(result['errors'][0]['code'],'storage_limit')
        with self.assertRaises(APIError):gateway.asset('a',job['id'],0)

    def test_restart_marks_reserved_job_failed_without_repeating_it(self):
        config=self.config();gateway=Gateway(config);jid='c'*32
        with gateway.lock:
            gateway.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)',(jid,'a',None,time.time(),None,'reserved','fingerprint','crash-key-1','[]',None,None));gateway.db.commit()
        gateway.close();reopened=Gateway(config);self.hosts.append(reopened)
        result=reopened.get('a',jid)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['errors'][0]['code'],'server_restarted')
        self.assertEqual(reopened.service.list_jobs(),[])

    def test_http_rejects_oversized_and_chunked_bodies(self):
        gateway,server=self.start_http()
        self.assertEqual(self.request(server,'POST','/v1/jobs',b'{}',**{'Content-Type':'application/json','Content-Length':'999999'})[0],413)
        self.assertEqual(self.request(server,'POST','/v1/jobs',b'{}',**{'Content-Type':'application/json','Transfer-Encoding':'chunked'})[0],400)

    def test_mcp_unsupported_versions_malformed_params_and_unknown_tools(self):
        gateway=self.gateway('mcp',accounts=[]);protocol=Protocol(gateway)
        error=protocol.handle({'jsonrpc':'2.0','id':1,'method':'server/discover','params':{'_meta':{'io.modelcontextprotocol/protocolVersion':'2099-01-01'}}})
        self.assertEqual(error['error']['code'],-32022)
        self.assertEqual(protocol.handle([])['error']['code'],-32600)
        unknown=protocol.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'_meta':{'io.modelcontextprotocol/protocolVersion':MODERN},'name':'unknown'}})
        self.assertEqual(unknown['error']['code'],-32602)

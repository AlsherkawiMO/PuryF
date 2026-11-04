# SPDX-License-Identifier: MIT
"""Newline-delimited stdio MCP. Async jobs use explicit status/cancel tools."""
import contextlib
import json
import sys

from . import __version__
from .access import APIError,load_config,object_fields
from .gateway import Gateway

MODERN='2026-07-28'
LEGACY=('2025-11-25','2025-06-18','2025-03-26')

def schema(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
STRING={'type':'string'}
INPUTS={'type':'array','items':STRING,'minItems':1,'maxItems':100}
OPTIONS={'type':'object','description':'ConversionOptions except output_folder, overwrite and password fields'}
TOOLS=[
 {'name':'puryf_convert','description':'Submit local files from permitted folders for PDF conversion. Returns a job ID; poll puryf_job_status.',
  'inputSchema':schema({'inputs':INPUTS,'options':OPTIONS},('inputs',))},
 {'name':'puryf_merge','description':'Merge PDF files in supplied order; returns a background job ID.',
  'inputSchema':schema({'inputs':INPUTS,'input_password':STRING,'output_password':STRING},('inputs',))},
 {'name':'puryf_split','description':'Extract pages or split one PDF every N pages; choose pages or every.',
  'inputSchema':schema({'inputs':{'type':'array','items':STRING,'minItems':1,'maxItems':1},'pages':STRING,'every':{'type':'integer','minimum':1,'maximum':1000},'input_password':STRING,'output_password':STRING},('inputs',))},
 {'name':'puryf_dependencies','description':'Check dependencies for permitted local files without converting.',
  'inputSchema':schema({'inputs':INPUTS},('inputs',))},
 {'name':'puryf_capabilities','description':'List format capabilities and integration limits.','inputSchema':schema({})},
 {'name':'puryf_job_status','description':'Poll a job for progress, errors, and output filenames.','inputSchema':schema({'job_id':STRING},('job_id',))},
 {'name':'puryf_cancel','description':'Cancel a submitted job. An active synchronous Office call must return first.','inputSchema':schema({'job_id':STRING},('job_id',))},
 {'name':'puryf_results','description':'Return verified local PDF output paths for a completed job.','inputSchema':schema({'job_id':STRING},('job_id',))}
]

class Protocol:
    def __init__(self,gateway):self.gateway=gateway;self.legacy=None;self.ready=False
    def call(self,name,args):
        tool=next((t for t in TOOLS if t['name']==name),None)
        if tool is None:raise LookupError('Unknown tool')
        object_fields(args,tool['inputSchema']['properties'],tool['inputSchema']['required'])
        if name in ('puryf_convert','puryf_merge','puryf_split'):
            result,_=self.gateway.submit('mcp',{'operation':name.removeprefix('puryf_'),**args})
            return result
        if name=='puryf_dependencies':return self.gateway.dependencies('mcp',args['inputs'])
        if name=='puryf_capabilities':return self.gateway.capabilities()
        if not isinstance(args['job_id'],str):raise ValueError('job_id must be a string')
        if name=='puryf_cancel':return self.gateway.cancel('mcp',args['job_id'])
        result=self.gateway.get('mcp',args['job_id'])
        if name=='puryf_results':
            return {'id':result['id'],'status':result['status'],'outputs':[
                {'index':o['index'],'path':str(self.gateway.asset('mcp',args['job_id'],o['index']))} for o in result['outputs']]}
        return result

    def handle(self,message):
        rid=message.get('id') if isinstance(message,dict) else None
        def response(value):return {'jsonrpc':'2.0','id':rid,'result':value}
        def error(code,text,data=None):
            result={'jsonrpc':'2.0','id':rid,'error':{'code':code,'message':text}}
            if data is not None:result['error']['data']=data
            return result
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or not isinstance(message.get('method'),str):return error(-32600,'Invalid Request')
        if 'id' in message and (isinstance(rid,bool) or not isinstance(rid,(str,int))):return error(-32600,'Invalid request ID')
        method=message['method'];params=message.get('params',{})
        if not isinstance(params,dict):return error(-32602,'Invalid params') if 'id' in message else None
        if 'id' not in message:
            if method=='notifications/initialized':self.ready=True
            # All tools return quickly. Completed submission requests no longer
            # have in-flight work to cancel; cancel jobs using puryf_cancel.
            return None
        version=params.get('_meta',{}).get('io.modelcontextprotocol/protocolVersion') if isinstance(params.get('_meta',{}),dict) else None
        modern=version is not None
        if modern and version!=MODERN:return error(-32022,'Unsupported protocol version',{'requested':version,'supported':[MODERN]})
        if method=='initialize':
            if modern:return error(-32601,'Use server/discover for modern MCP')
            requested=params.get('protocolVersion')
            self.legacy=requested if requested in LEGACY else LEGACY[0]
            return response({'protocolVersion':self.legacy,'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'puryf','version':__version__}})
        if method=='server/discover':
            if not modern:return error(-32602,'Modern requests require protocolVersion metadata')
            return response({'resultType':'complete','supportedVersions':[MODERN],'capabilities':{'tools':{'listChanged':False}},'cacheScope':'private','ttlMs':0})
        if not modern and (not self.legacy or not self.ready):return error(-32600,'Initialize the legacy session first')
        if method=='ping':return response({'resultType':'complete'} if modern else {})
        if method=='tools/list':return response({'tools':TOOLS,**({'resultType':'complete','cacheScope':'private','ttlMs':0} if modern else {})})
        if method!='tools/call':return error(-32601,'Method not found')
        if not isinstance(params.get('name'),str):return error(-32602,'Tool name is required')
        try:
            value=self.call(params['name'],params.get('arguments',{}))
            return response({'content':[{'type':'text','text':json.dumps(value,ensure_ascii=True)}],'structuredContent':value,
                             'isError':False,**({'resultType':'complete'} if modern else {})})
        except LookupError:return error(-32602,'Unknown tool')
        except (APIError,ValueError,TypeError) as issue:
            value={'code':getattr(issue,'code','invalid_arguments'),'message':str(issue)}
            return response({'content':[{'type':'text','text':json.dumps(value)}],'isError':True,**({'resultType':'complete'} if modern else {})})
        except Exception:return error(-32603,'Internal tool error')

def run(config_file):
    config=load_config(config_file)
    if config['mode']!='mcp':raise ValueError('stdio MCP requires mode: mcp')
    output=sys.stdout;source=sys.stdin.buffer
    with contextlib.redirect_stdout(sys.stderr):
        gateway=Gateway(config);protocol=Protocol(gateway)
        try:
            while True:
                line=source.readline(1024*1024+1)
                if not line:break
                if len(line)>1024*1024:break
                try:message=json.loads(line);result=protocol.handle(message)
                except (ValueError,UnicodeError):result={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
                if result is not None:output.write(json.dumps(result,ensure_ascii=True)+'\n');output.flush()
        except KeyboardInterrupt:pass
        finally:gateway.close()

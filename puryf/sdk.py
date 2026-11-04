# SPDX-License-Identifier: MIT
"""Public Python SDK. Jobs remain cancellable, inspectable and asynchronous."""
import queue
import threading
from pathlib import Path
from .engine import APP_DIR
from .jobs import ConversionService,TERMINAL
from .options import ConversionOptions
from .state import Store

class Client:
    def __init__(self,root=None,service=None):
        self.store=Store(root or APP_DIR);self.service=service or ConversionService(reports_dir=self.store.root/'Reports')
        self.owns_service=service is None;self.events=self.service.subscribe();self.stop=threading.Event()
        self.tracker=threading.Thread(target=self._track,name='PuryF-History',daemon=True);self.tracker.start()
    def _track(self):
        while not self.stop.is_set():
            try:event=self.events.get(timeout=.1)
            except queue.Empty:continue
            if event['type']=='job_finished':
                try:self.store.record(self.service.get_job(event['job_id']))
                except (KeyError,OSError):pass
    def options(self,options=None,preset=None):
        value=self.store.preset(preset) if preset else {}
        if isinstance(options,ConversionOptions):options=options.engine_settings()
        value.update(options or {});return ConversionOptions.from_mapping(value)
    def convert(self,inputs,options=None,preset=None):return self.service.submit_conversion(inputs,self.options(options,preset),origin='sdk')
    def merge(self,inputs,output,options=None):return self.service.submit_merge(inputs,output,options,origin='sdk')
    def split(self,source,**kwargs):return self.service.submit_split(source,origin='sdk',**kwargs)
    def document(self,inputs,spec,password=''):return self.service.submit_document(inputs,spec,origin='sdk',password=password)
    def doctor(self,inputs,options=None):return self.service.check_dependencies(inputs,options)
    def pause(self):self.service.pause()
    def resume(self):self.service.resume()
    def repeat(self,jid):
        record=next((j for j in self.store.history(1000) if j['id']==jid),None)
        if record is None:raise ValueError('History entry not found')
        if record.get('requires_output_password'):raise ValueError('Re-enter the output password in a new job; passwords are never stored in history')
        paths=[i['source'] for i in record['inputs']]
        if record['operation']=='convert':return self.convert(paths,record['options'])
        if record['operation']=='document':
            if record['parameters'].get('action')=='text':raise ValueError('Repeat text extraction explicitly; reviewed text is not stored')
            return self.document(paths,record['parameters'])
        if record['operation']=='merge':return self.service.submit_merge(paths,record['parameters']['output_file'],record['options'],origin='sdk')
        if record['operation']=='split':return self.service.submit_split(paths[0],record['options'],origin='sdk',**record['parameters'])
        raise ValueError('Unsupported repeat operation')
    def close(self):
        if self.owns_service:self.service.close()
        # Flush completed records synchronously before stopping the tracker.
        for job in self.service.list_jobs():
            if job['status'] in TERMINAL:self.store.record(job)
        self.stop.set();self.tracker.join();self.service.unsubscribe(self.events)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

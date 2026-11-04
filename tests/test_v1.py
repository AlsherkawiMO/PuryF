"""V1 documents, presets/history, automation, extensions, pause and CLI regression tests."""
import gc
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
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pypdf import PdfReader,PdfWriter
from PIL import Image
from reportlab.pdfgen.canvas import Canvas
from puryf.jobs import ConversionService
from puryf import documents,engine
from puryf.options import ConversionOptions
from puryf.sdk import Client
from puryf.state import Store,duplicates

class V1Tests(unittest.TestCase):
    def setUp(self):
        gc.collect();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.service=ConversionService(reports_dir=self.root/'Reports')
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def pdf(self,name='source.pdf',pages=3):
        path=self.root/name;canvas=Canvas(str(path),pagesize=(200,300))
        canvas.setTitle('Original title');canvas.setAuthor('Author')
        for i in range(pages):canvas.drawString(20,100,f'Page {i+1}');canvas.showPage()
        canvas.save();return path
    def text(self,name='source.txt',value='PuryF v1'):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value);return path
    def run_doc(self,path,spec):
        result=self.service.submit_document(path if isinstance(path,list) else [path],spec).wait(10)
        self.assertEqual(result['status'],'succeeded',result['errors']);return result
    def test_compose_reorder_rotation_delete_extract_and_source_unchanged(self):
        source=self.pdf();original=source.read_bytes();output=self.root/'arranged.pdf'
        self.run_doc(source,{'action':'compose','output':str(output),'pages':[{'source':0,'page':2,'rotation':90},{'source':0,'page':0}]})
        reader=PdfReader(output);self.assertEqual(len(reader.pages),2);self.assertEqual(reader.pages[0].rotation,90)
        self.assertIn('Page 3',reader.pages[0].extract_text());self.assertIn('Page 1',reader.pages[1].extract_text())
        self.assertEqual(source.read_bytes(),original)
    def test_course_pack_contents_links_bookmarks_numbering(self):
        a=self.pdf('a.pdf',2);b=self.pdf('b.pdf',1);output=self.root/'course.pdf'
        self.run_doc([a,b],{'action':'compose','output':str(output),'course_pack':True,'title':'Training course'})
        reader=PdfReader(output);self.assertEqual(len(reader.pages),4)
        self.assertIn('Training course',reader.pages[0].extract_text())
        self.assertIn('1 / 4',reader.pages[0].extract_text());self.assertTrue(reader.pages[0].get('/Annots'))
        self.assertGreaterEqual(len(reader.outline),3)
    def test_watermark_header_footer_logo_and_numbers(self):
        source=self.pdf();logo=self.root/'logo.png';Image.new('RGB',(80,40),'orange').save(logo)
        output=self.root/'stamped.pdf';self.run_doc(source,{'action':'decorate','output':str(output),'watermark':'DRAFT','header':'Header','footer':'Footer','logo':str(logo),'page_numbers':True})
        text=PdfReader(output).pages[0].extract_text();self.assertIn('DRAFT',text);self.assertIn('Header',text);self.assertIn('1 / 3',text)
    def test_metadata_edit_remove_and_inspection(self):
        source=self.pdf();info=documents.inspect(source);self.assertEqual(info['metadata']['/Title'],'Original title')
        output=self.root/'metadata.pdf';self.run_doc(source,{'action':'metadata','output':str(output),'metadata':{'Title':'New title','Author':'New author'}})
        self.assertEqual(PdfReader(output).metadata.title,'New title')
        clean=self.root/'clean.pdf';self.run_doc(output,{'action':'metadata','output':str(clean),'remove_metadata':True})
        self.assertFalse(PdfReader(clean).metadata)
    def test_pdf_preview_export_png_jpeg_and_text(self):
        source=self.pdf();image=documents.render(source,1,width=200);self.assertEqual(image.size,(200,300))
        for kind in ('png','jpeg'):
            result=self.run_doc(source,{'action':'export','output_dir':str(self.root/kind),'format':kind,'pages':'2-3','dpi':72})
            self.assertEqual(len(result['outputs']),2)
            with Image.open(result['outputs'][0]['path']) as exported:self.assertEqual(exported.size,(200,300))
        output=self.root/'text.txt';self.run_doc(source,{'action':'text','output':str(output)})
        self.assertIn('Page 2',output.read_text())
        reviewed=self.root/'reviewed.txt';self.run_doc(source,{'action':'text','output':str(reviewed),'reviewed_text':'نص عربي مصحح'})
        self.assertEqual(reviewed.read_text(),'نص عربي مصحح')
    def test_best_effort_target_compression_reports_actual_result(self):
        source=self.pdf();output=self.root/'compressed.pdf'
        result=self.run_doc(source,{'action':'compress','output':str(output),'target_bytes':100000,'allow_raster':False})
        details=result['outputs'][0]['details'];self.assertTrue(details['target_met']);self.assertEqual(details['actual_bytes'],output.stat().st_size)
        tiny=self.run_doc(source,{'action':'compress','output':str(self.root/'tiny.pdf'),'target_bytes':1024,'allow_raster':True})
        self.assertIn('target_met',tiny['outputs'][0]['details'])
    def test_document_jobs_protect_sources_existing_outputs_and_invalid_refs(self):
        source=self.pdf();original=source.read_bytes()
        result=self.service.submit_document([source],{'action':'metadata','output':str(source),'remove_metadata':True}).wait(5)
        self.assertEqual(result['status'],'failed');self.assertEqual(source.read_bytes(),original)
        output=self.root/'out.pdf';output.write_bytes(b'keep')
        result=self.service.submit_document([source],{'action':'compose','output':str(output)}).wait(5)
        self.assertEqual(result['status'],'failed');self.assertEqual(output.read_bytes(),b'keep')
        result=self.service.submit_document([source],{'action':'compose','output':str(self.root/'bad.pdf'),'pages':[{'source':9,'page':0}]}).wait(5)
        self.assertEqual(result['status'],'failed')
    def test_pause_between_files_then_resume(self):
        self.service.pause();source=self.text();handle=self.service.submit_conversion([source]);time.sleep(.15)
        self.assertEqual(handle.snapshot()['status'],'queued');self.assertFalse(source.with_suffix('.pdf').exists())
        self.service.resume();self.assertEqual(handle.wait(5)['status'],'succeeded')
    def test_cancel_while_paused_closes_cleanly(self):
        self.service.pause();handle=self.service.submit_conversion([self.text()]);self.assertTrue(handle.cancel())
        self.assertEqual(handle.wait(3)['status'],'cancelled')
    def test_naming_preserved_folders_hash_and_quality(self):
        source=self.text('tree/unit/notes.txt')
        options=ConversionOptions(output_folder=str(self.root/'out'),source_root=str(self.root/'tree'),preserve_folders=True,naming_pattern='{index}-{stem}-{hash8}')
        result=self.service.submit_conversion([source],options).wait(5);self.assertEqual(result['status'],'succeeded',result['errors'])
        output=Path(result['outputs'][0]['path']);self.assertEqual(output.parent,self.root/'out/unit');self.assertTrue(output.name.startswith('1-notes-'))
        for pattern in ('../{stem}','{stem.__class__}','{index:999999}','CON'):
            try:
                bad=ConversionOptions(output_folder=str(self.root/'bad'),naming_pattern=pattern)
                result=self.service.submit_conversion([source],bad).wait(5);self.assertEqual(result['status'],'failed')
            except ValueError:pass
    def test_content_duplicates_preflight_and_preset_password_omission(self):
        a=self.text('a.txt');b=self.text('b.txt');self.assertEqual(len(duplicates([a,b])),1)
        store=Store(self.root/'state');store.save_preset('Training',{'password_pdf':True,'pdf_password':'never-save','image_max_edge':1400})
        self.assertNotIn('pdf_password',store.preset('Training'));self.assertNotIn('password_pdf',store.preset('Training'))
        self.assertEqual(store.preset('Small')['image_max_edge'],1400)
        checks=self.service.check_dependencies([a]);self.assertTrue(checks[0]['ready'])
    def test_sdk_history_repeat_recent_folders_and_redacted_diagnostics(self):
        source=self.text('private-name.txt')
        with Client(self.root/'state') as client:
            handle=client.convert([source],{'output_folder':str(self.root/'out')},preset='Balanced');self.assertEqual(handle.wait(5)['status'],'succeeded')
        store=Store(self.root/'state');entry=store.history()[0];self.assertEqual(entry['id'],handle.id)
        self.assertTrue(store.get('recent_output_folders'))
        diagnostic=json.dumps(store.diagnostic());self.assertNotIn(str(self.root),diagnostic);self.assertNotIn(source.name,diagnostic)
        with Client(self.root/'state') as client:self.assertEqual(client.repeat(handle.id).wait(5)['status'],'skipped')
    def test_watch_stability_hash_dedupe_and_changed_content(self):
        from puryf.automation import Runner
        watched=self.root/'watch';watched.mkdir();source=watched/'notes.txt';source.write_text('Version 1')
        runner=Runner({'state_dir':str(self.root/'auto'),'watches':[{'name':'training','folder':str(watched),'output':str(self.root/'out')}]})
        try:
            runner.tick();self.assertEqual(runner.client.service.list_jobs(),[])
            runner.tick();jobs=runner.client.service.list_jobs();self.assertEqual(len(jobs),1);runner.client.service.wait(jobs[0]['id'],5);runner.tick()
            runner.tick();self.assertEqual(len(runner.client.service.list_jobs()),1)
            source.write_text('Version 2');runner.tick();runner.tick();jobs=runner.client.service.list_jobs();self.assertEqual(len(jobs),2);runner.client.service.wait(jobs[-1]['id'],5)
            self.assertEqual(len(list((self.root/'out').glob('*.pdf'))),2)
        finally:runner.close()
    def test_schedule_once_per_bucket_and_background_control(self):
        from puryf.automation import Runner,control
        source=self.text();manifest=self.root/'batch.json';manifest.write_text(json.dumps({'version':1,'command':'convert','inputs':[str(source)],'options':{'output_folder':str(self.root/'out')}}))
        runner=Runner({'state_dir':str(self.root/'auto'),'schedules':[{'name':'daily','every_seconds':60,'request':str(manifest)}]})
        try:
            runner.tick(120);runner.tick(121);self.assertEqual(len(runner.client.service.list_jobs()),1)
            runner.client.service.wait(runner.client.service.list_jobs()[0]['id'],5)
            control(self.root/'auto','pause');runner.tick(122);self.assertTrue(runner.client.service.paused)
            control(self.root/'auto','resume');runner.tick(123);self.assertFalse(runner.client.service.paused)
            control(self.root/'auto','stop');runner.tick(124);self.assertTrue(runner.closed)
        finally:runner.close()
    def test_explicit_converter_extension_writes_staged_pdf(self):
        from puryf.extensions import load
        plugin=self.root/'converter.py';plugin.write_text("API_VERSION=1\nEXTENSIONS=['.v1demo']\ndef convert(source, output, settings, log, cancel):\n from reportlab.pdfgen.canvas import Canvas\n c=Canvas(str(output));c.drawString(10,100,source.read_text());c.save()\n")
        load(plugin)
        try:
            source=self.text('example.v1demo');result=self.service.submit_conversion([source]).wait(5)
            self.assertEqual(result['status'],'succeeded',result['errors'])
        finally:engine.PLUGIN_CONVERTERS.pop('.v1demo');engine.ALL_EXTS.discard('.v1demo')
    def test_v1_cli_document_inspect_preset_and_preflight(self):
        source=self.pdf();spec=self.root/'doc.json';spec.write_text(json.dumps({'action':'compose','output':'cli-output.pdf','pages':[{'source':0,'page':1}]}))
        env=dict(os.environ,PYTHONPATH=str(ROOT)+os.pathsep+os.environ.get('PYTHONPATH',''))
        for args,key in [(['document',str(source),'--spec',str(spec)],'result'),(['inspect',str(source)],'inspection'),(['preset','list'],'presets'),(['preflight',str(source)],'preflight')]:
            result=subprocess.run([sys.executable,'-m','puryf','--state-dir',str(self.root/'state'),*args,'--json'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn(key,json.loads(result.stdout))
        self.assertEqual(len(PdfReader(self.root/'cli-output.pdf').pages),1)

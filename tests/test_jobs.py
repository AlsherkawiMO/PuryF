"""Behavioral tests of the shared service, without importing any GUI module."""
import importlib.abc
import gc
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from puryf import ConversionOptions, ConversionService, get_default_service
from puryf import engine
from pypdf import PdfReader, PdfWriter


class JobTests(unittest.TestCase):
    def setUp(self):
        # unittest releases each completed GUI case before this setup. Dispose
        # its interpreter here, before a headless worker can trigger cyclic GC.
        gc.collect()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = ConversionService(reports_dir=self.root / 'Reports')

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def text(self, name='notes.txt', content='Training notes'):
        path = self.root / name; path.write_text(content, encoding='utf-8'); return path

    def pdf(self, name='source.pdf', pages=3):
        path = self.root / name; w = PdfWriter()
        for i in range(pages): w.add_blank_page(width=200+i, height=300)
        w.write(path); return path

    def test_import_and_conversion_without_tk_or_display(self):
        script = '''import sys, importlib.abc, json
class BlockGUI(importlib.abc.MetaPathFinder):
 def find_spec(self, name, path=None, target=None):
  if name.split('.')[0] in ('tkinter','tkinterdnd2'):
   raise ImportError('GUI imports forbidden in core')
sys.meta_path.insert(0, BlockGUI())
from puryf import ConversionService, ConversionOptions
from pathlib import Path
with ConversionService(reports_dir=Path(sys.argv[2])/'Reports') as service:
 result=service.submit_conversion([sys.argv[1]], ConversionOptions(output_folder=sys.argv[2])).wait(10)
 assert result['status']=='succeeded', result
 assert 'tkinter' not in sys.modules
 print(json.dumps(result))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.text()), str(self.root/'out')],
            cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'succeeded')

    def test_options_are_validated_and_password_not_in_repr(self):
        for options in [{'overwrite':'yes'}, {'image_paper':'A5'}, {'command_timeout':False},
                        {'password_pdf':True}, {'unknown':1}]:
            with self.assertRaises(ValueError): self.service.submit_conversion([self.text()], options)
        self.assertNotIn('secret', repr(ConversionOptions(pdf_password='secret')))

    def test_real_job_snapshot_results_report_and_event_isolation(self):
        events = self.service.subscribe()
        handle = self.service.submit_conversion([self.text()], {'output_folder':str(self.root/'out')}, origin='api')
        result = handle.wait(10)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['origin'], 'api')
        self.assertEqual(result['progress']['percent'], 100)
        self.assertIsNotNone(result['started_at']); self.assertIsNotNone(result['finished_at'])
        self.assertTrue(Path(result['report']).is_file())
        self.assertIn('Training', PdfReader(result['outputs'][0]['path']).pages[0].extract_text())
        types = []
        while not events.empty(): types.append(events.get()['type'])
        self.assertIn('item_updated', types); self.assertIn('job_finished', types)
        result['outputs'].clear(); result['options']['overwrite'] = True
        self.assertEqual(len(handle.snapshot()['outputs']), 1)
        self.assertFalse(handle.snapshot()['options']['overwrite'])
        json.dumps(handle.snapshot())

    def test_partial_batch_has_structured_errors_and_continues(self):
        handle = self.service.submit_conversion([self.root/'missing.txt', self.text(), self.text('no.xyz')])
        result = handle.wait(10)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([i['status'] for i in result['inputs']], ['Failed','Success','Failed'])
        self.assertEqual({e['code'] for e in result['errors']}, {'missing_source','unsupported_format'})
        self.assertEqual(result['progress']['completed'], 3)

    def test_missing_office_dependency_is_reported_without_attempt(self):
        source = self.text('document.docx')
        with patch.object(engine, 'office_available', return_value=False):
            checks = self.service.check_dependencies([source])
            self.assertFalse(checks[0]['ready'])
            result = self.service.submit_conversion([source]).wait(10)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['code'], 'dependency_missing')

    def test_option_snapshot_isolated_from_caller_and_secrets_not_exported(self):
        options = {'output_folder':str(self.root/'out'), 'password_pdf':True, 'pdf_password':'private-password'}
        handle = self.service.submit_conversion([self.text()], options)
        options['pdf_password'] = 'changed'; options['overwrite'] = True
        result = handle.wait(10)
        self.assertNotIn('private-password', json.dumps(result))
        self.assertTrue(result['options']['password_pdf'])
        self.assertTrue(result['options']['password_supplied'])
        self.assertNotIn('pdf_password', result['options'])
        r = PdfReader(result['outputs'][0]['path'])
        self.assertTrue(r.decrypt('private-password'))

    def test_collisions_and_originals_preserved(self):
        source = self.pdf(); original = source.read_bytes()
        result = self.service.submit_conversion([source], {'overwrite':True}).wait(10)
        self.assertEqual(source.read_bytes(), original)
        self.assertNotEqual(result['outputs'][0]['path'], str(source))
        first = self.service.submit_conversion([self.text('a.txt')]).wait(10)
        second = self.service.submit_conversion([self.root/'a.txt']).wait(10)
        self.assertEqual(second['status'], 'skipped')
        self.assertEqual(first['outputs'][0]['path'], str(self.root/'a.pdf'))

    def test_merged_batch_and_manual_pdf_operations_share_service(self):
        result = self.service.submit_conversion([self.text('one.txt'), self.text('two.txt')], {'merge_pdf':True}).wait(10)
        merged = next(o['path'] for o in result['outputs'] if o['kind']=='merged')
        self.assertEqual(len(PdfReader(merged).pages), 2)
        split = self.service.submit_split(merged, output_file=self.root/'part.pdf', page_ranges='2').wait(10)
        self.assertEqual(split['status'], 'succeeded')
        self.assertEqual(len(PdfReader(split['outputs'][0]['path']).pages), 1)
        manual = self.service.submit_merge([merged, self.root/'part.pdf'], self.root/'combined.pdf').wait(10)
        self.assertEqual(manual['status'], 'succeeded')
        self.assertEqual(len(PdfReader(self.root/'combined.pdf').pages), 3)

    def test_interval_split_and_existing_output_refusal(self):
        source = self.pdf(pages=5)
        result = self.service.submit_split(source, every_n=2, output_dir=self.root/'parts').wait(10)
        self.assertEqual([len(PdfReader(o['path']).pages) for o in result['outputs']], [2,2,1])
        repeat = self.service.submit_split(source, every_n=2, output_dir=self.root/'parts').wait(10)
        self.assertEqual(repeat['status'], 'failed')
        self.assertEqual(repeat['errors'][0]['code'], 'output_exists')

    def test_manual_tools_refuse_source_replacement(self):
        source = self.pdf(); before = source.read_bytes()
        result = self.service.submit_merge([source], source, {'overwrite':True}).wait(10)
        self.assertEqual(result['status'], 'failed'); self.assertEqual(source.read_bytes(), before)
        result = self.service.submit_split(source, {'overwrite':True}, output_file=source, page_ranges='1').wait(10)
        self.assertEqual(result['status'], 'failed'); self.assertEqual(source.read_bytes(), before)

    def test_cancellation_at_commit_never_saves_staged_output(self):
        from contextlib import contextmanager
        stop = threading.Event()
        backend = engine.ConverterEngine(ConversionOptions().engine_settings(), lambda *a:None,
                lambda *a:None, lambda *a:None, stop, reports_dir=self.root/'Reports')
        @contextmanager
        def cancel_at_commit(path):
            stop.set()
            yield
        backend.commit_guard = cancel_at_commit
        source = self.text('cancel-at-commit.txt')
        with self.assertRaises(engine.ConversionCancelled): backend.convert(source)
        self.assertFalse(source.with_suffix('.pdf').exists())

    def test_invalid_jobs_are_rejected_before_queueing(self):
        with self.assertRaises(ValueError): self.service.submit_conversion([])
        with self.assertRaises(ValueError): self.service.submit_split(self.pdf(), every_n=0, output_dir=self.root)
        with self.assertRaises(ValueError): self.service.submit_conversion([self.text()], item_ids=[])
        with self.assertRaises(ValueError): self.service.submit_merge([self.pdf()], self.root/'x.pdf', {'ocr_pdf':True})
        self.assertEqual(self.service.list_jobs(), [])

    def _blocking_service(self):
        self.service.close()
        entered = threading.Event(); release = threading.Event(); calls = []
        class BlockingEngine(engine.ConverterEngine):
            def convert(inner, source):
                calls.append((source.name, threading.get_ident()))
                if source.name == 'block.txt':
                    entered.set()
                    if not release.wait(10): raise RuntimeError('Test release timed out')
                return super().convert(source)
        self.service = ConversionService(self.root/'Reports', engine_factory=BlockingEngine)
        self.addCleanup(release.set)
        return entered, release, calls

    def test_fifo_across_adapters_and_queued_cancellation(self):
        entered, release, calls = self._blocking_service()
        a = self.service.submit_conversion([self.text('block.txt')], origin='desktop')
        self.assertTrue(entered.wait(5))
        b = self.service.submit_conversion([self.text('skip.txt')], origin='explorer')
        c = self.service.submit_conversion([self.text('last.txt')], origin='mcp')
        self.assertTrue(b.cancel()); self.assertEqual(b.wait(1)['status'], 'cancelled')
        release.set(); self.assertEqual(a.wait(10)['status'], 'succeeded'); self.assertEqual(c.wait(10)['status'], 'succeeded')
        self.assertEqual([n for n,t in calls], ['block.txt','last.txt'])
        self.assertEqual(len({t for n,t in calls}), 1)
        self.assertNotEqual(calls[0][1], threading.get_ident())

    def test_running_cancellation_and_timeout(self):
        entered, release, calls = self._blocking_service()
        handle = self.service.submit_conversion([self.text('block.txt'),self.text('later.txt')])
        self.assertTrue(entered.wait(5))
        with self.assertRaises(TimeoutError): handle.wait(.01)
        handle.cancel(); release.set()
        result = handle.wait(10)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual([i['status'] for i in result['inputs']], ['Cancelled','Cancelled'])
        self.assertFalse((self.root/'block.pdf').exists()); self.assertFalse((self.root/'later.pdf').exists())

    def test_queued_source_protected_across_jobs(self):
        entered, release, calls = self._blocking_service()
        # First job wants block.pdf; the next job will use that existing file as a source.
        original_pdf = self.pdf('block.pdf'); original = original_pdf.read_bytes()
        first = self.service.submit_conversion([self.text('block.txt')], {'overwrite':True})
        self.assertTrue(entered.wait(5))
        later = self.service.submit_conversion([original_pdf])
        release.set(); result = first.wait(10); later.wait(10)
        # This source arrived after the first job selected its destination.
        # The commit guard must refuse replacement, even with overwrite enabled.
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(original_pdf.read_bytes(), original)
        self.assertIn('queued source', result['errors'][0]['message'])

    def test_close_cancels_pending_and_rejects_new_jobs(self):
        entered, release, calls = self._blocking_service()
        a = self.service.submit_conversion([self.text('block.txt')]); self.assertTrue(entered.wait(5))
        b = self.service.submit_conversion([self.text('never.txt')])
        self.service.close(wait=False)
        self.assertEqual(b.wait(1)['status'], 'cancelled')
        with self.assertRaises(RuntimeError): self.service.submit_conversion([self.text()])
        release.set(); self.service.close(); self.assertEqual(a.wait(1)['status'], 'cancelled')

    def test_office_initialization_calls_and_cleanup_have_one_owner_thread(self):
        trace = []
        class FakeCOM:
            @staticmethod
            def CoInitialize(): trace.append(('init',threading.get_ident()))
            @staticmethod
            def CoUninitialize(): trace.append(('uninit',threading.get_ident()))
        class OfficeEngine(engine.ConverterEngine):
            def _convert_to(inner, source, output):
                inner.init_com()
                class App:
                    def Quit(self): trace.append(('quit',threading.get_ident()))
                inner.word = App(); trace.append(('convert',threading.get_ident()))
                w=PdfWriter(); w.add_blank_page(width=100,height=100); w.write(output)
                return output
        self.service.close(); self.service=ConversionService(self.root/'Reports',engine_factory=OfficeEngine)
        with patch.object(engine,'pythoncom',FakeCOM), patch.object(engine,'win32com',object()), patch.object(engine,'office_available',return_value=True):
            jobs=[self.service.submit_conversion([self.text(f'office{i}.docx')]) for i in range(2)]
            for job in jobs: self.assertEqual(job.wait(10)['status'],'succeeded')
        self.assertEqual([n for n,t in trace], ['init','convert','quit','uninit']*2)
        self.assertEqual(len({t for n,t in trace}),1)
        self.assertNotEqual(trace[0][1],threading.get_ident())

    def test_default_service_reused_within_one_owner_process(self):
        first = get_default_service(self.root/'DefaultReports')
        try: self.assertIs(first, get_default_service())
        finally: first.close()


if __name__ == '__main__': unittest.main()

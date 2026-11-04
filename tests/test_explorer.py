"""Explorer mailbox, concurrent process handoff, and real desktop conversions."""
import json
import gc
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from puryf.explorer import Inbox, InstanceLock, parse_args, validate_request

ROOT = Path(__file__).resolve().parents[1]

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = Inbox(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lightweight_import(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys; import puryf.explorer; assert not any(n in sys.modules for n in ('tkinter','puryf.engine','PIL','puryf.desktop'))"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_arguments_and_literal_option_filename(self):
        self.assertEqual(parse_args([]), ('show', []))
        self.assertEqual(parse_args(['--explorer-queue', '--', '--fun.txt']), ('queue', ['--fun.txt']))
        with patch('sys.stderr'), self.assertRaises(SystemExit): parse_args(['--explorer-convert'])
        with patch('sys.stderr'), self.assertRaises(SystemExit): parse_args(['unqualified.txt'])

    def test_atomic_requests_coalesce_and_keep_action_order(self):
        paths = [self.root / f'فكرة & (notes) {i}.txt' for i in range(4)]
        requests = [self.inbox.publish('convert', [paths[0]]), self.inbox.publish('convert', [paths[1]]),
                    self.inbox.publish('queue', [paths[2]]), self.inbox.publish('convert', [paths[3]])]
        calls = []; errors = []
        self.inbox.drain(calls.append, errors.append)
        self.assertFalse(errors)
        self.assertEqual([d['action'] for d in calls], ['convert', 'queue', 'convert'])
        self.assertEqual(calls[0]['paths'], list(map(str, paths[:2])))
        self.assertTrue(all(not p.exists() for p in requests))

    def test_transient_failure_is_not_acknowledged(self):
        path = self.inbox.publish('queue', [self.root/'a.txt'])
        def fail(data): raise RuntimeError('Closing')
        self.inbox.drain(fail, lambda x: None)
        self.assertTrue(path.exists())
        self.inbox.drain(lambda x: None, lambda x: None)
        self.assertFalse(path.exists())

    def test_invalid_and_oversized_requests_never_reach_handler(self):
        (self.inbox.pending/'bad.json').write_text('{broken')
        (self.inbox.pending/'huge.json').write_bytes(b'x' * (1024*1024+1))
        (self.inbox.pending/'incomplete.tmp').write_text('{')
        calls = []; errors = []
        self.inbox.drain(calls.append, errors.append)
        self.assertFalse(calls); self.assertEqual(len(errors), 2)
        self.assertTrue((self.inbox.pending/'incomplete.tmp').exists())
        for value in [{'version': True, 'action': 'show', 'paths': []},
                      {'version': 1, 'action': 'convert', 'paths': ['relative.txt']},
                      {'version': 1, 'action': 'queue', 'paths': [], 'command':'anything'}]:
            with self.assertRaises(ValueError): validate_request(value)

    def test_lock_exclusion_and_recovery_after_owner_death(self):
        script = "from puryf.explorer import InstanceLock; import sys,time; lock=InstanceLock(sys.argv[1]); assert lock.acquire(); print('ready',flush=True); time.sleep(30)"
        owner = subprocess.Popen([sys.executable, '-c', script, str(self.root)], cwd=ROOT,
                                 stdout=subprocess.PIPE, text=True)
        lock = InstanceLock(self.root)
        try:
            self.assertEqual(owner.stdout.readline().strip(), 'ready')
            self.assertFalse(lock.acquire())
            owner.kill(); owner.wait(timeout=5)
            self.assertTrue(lock.acquire())
        finally:
            if owner.poll() is None: owner.kill(); owner.wait()
            owner.stdout.close()
            lock.close()

    def test_concurrent_launchers_reuse_one_owner_and_deliver_all_paths(self):
        # A headless desktop stand-in exercises the real launcher/OS lock/mailbox
        # in separate processes. Real Tk + conversion are tested below.
        script = r'''
import json, os, sys, time, types
from pathlib import Path
from puryf.explorer import launch
root = Path(os.environ['LOCALAPPDATA'])
class App:
 def __init__(self):
  with (root/'windows.txt').open('a') as f: f.write('window\n')
 def attach_explorer(self, inbox): self.inbox=inbox
 def mainloop(self):
  deadline=time.monotonic()+3
  def receive(data):
   with (root/'received.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(data)+'\n')
  while time.monotonic()<deadline:
   self.inbox.drain(receive, lambda s: None); time.sleep(.01)
sys.modules['puryf.desktop']=types.SimpleNamespace(App=App)
raise SystemExit(launch(sys.argv[1:]))
'''
        env = dict(os.environ, LOCALAPPDATA=str(self.root))
        owner = subprocess.Popen([sys.executable, '-c', script], cwd=ROOT, env=env)
        clients = []
        try:
            deadline = time.monotonic()+5
            while not (self.root/'windows.txt').exists() and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue((self.root/'windows.txt').exists())
            paths = [str(self.root / f'قطة & notes {i}.txt') for i in range(20)]
            for path in paths:
                clients.append(subprocess.Popen([sys.executable, '-c', script, '--explorer-convert', '--', path], cwd=ROOT, env=env))
            for client in clients: self.assertEqual(client.wait(timeout=10), 0)
            self.assertEqual(owner.wait(timeout=10), 0)
            self.assertEqual((self.root/'windows.txt').read_text().splitlines(), ['window'])
            received = [json.loads(s) for s in (self.root/'received.jsonl').read_text().splitlines()]
            self.assertCountEqual([p for d in received for p in d['paths']], paths)
            self.assertFalse(list((self.root/'PuryF/Explorer/pending').glob('*.json')))
        finally:
            for proc in [owner, *clients]:
                if proc.poll() is None: proc.kill(); proc.wait()

class ExplorerDesktopTests(unittest.TestCase):
    def setUp(self):
        gc.collect()  # finish prior destroyed interpreters on the Tk owner thread
        from puryf import desktop
        self.p = desktop
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.patches = [patch.object(desktop, 'APP_DIR', self.root),
                        patch.object(desktop, 'STATE_PATH', self.root/'session.json'),
                        patch.object(desktop, 'REPORTS_DIR', self.root/'Reports')]
        for item in self.patches: item.start()
        self.app = desktop.App(); self.errors = []
        self.app.report_callback_exception = lambda *e: self.errors.append(e)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        for item in self.patches: item.stop()
        self.tmp.cleanup()
        self.assertFalse(self.errors, self.errors)

    def source(self, name='notes.txt'):
        path = self.root/name; path.write_text('PuryF Explorer conversion', encoding='utf-8'); return path

    def send(self, action, *paths):
        self.app.accept_explorer({'version':1, 'action':action, 'paths':list(map(str, paths))})

    def finish(self):
        deadline = time.monotonic()+10
        while self.app.service.busy and time.monotonic()<deadline:
            self.app.update(); time.sleep(.01)
        self.app._process_job_events(); self.app.update()
        self.assertFalse(self.app.service.busy)

    def test_queue_only_does_not_start_and_survives_session(self):
        source = self.source()
        self.send('queue', source, source)
        self.assertEqual(len(self.app.items), 1)
        self.assertEqual(self.app.items[0].status, 'Queued')
        self.assertEqual(self.app.service.list_jobs(), [])
        self.assertFalse(source.with_suffix('.pdf').exists())
        state = json.loads((self.root/'session.json').read_text())
        self.assertEqual(state['items'][0]['status'], 'Queued')

    def test_mixed_batch_uses_fixed_defaults_and_protects_sources(self):
        from PIL import Image
        from pypdf import PdfReader
        text = self.source('ملاحظات & notes.txt'); before = text.read_bytes()
        image = self.root/'cat image.png'; Image.new('RGB', (100,120), 'orange').save(image)
        held = self.source('held.txt'); self.send('queue', held)
        self.app.output_folder.set(str(self.root/'wrong-folder'))
        self.app.overwrite.set(True); self.app.merge_pdf.set(True)
        self.app.password_pdf.set(True); self.app.pdf_password.set('do-not-inherit')
        self.send('convert', text, image, text)
        self.finish()
        jobs = self.app.service.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['status'], 'succeeded')
        self.assertEqual(jobs[0]['origin'], 'explorer')
        self.assertEqual(len(jobs[0]['inputs']), 2)
        options = jobs[0]['options']
        self.assertFalse(options['overwrite']); self.assertFalse(options['password_pdf'])
        self.assertFalse(options['merge_pdf']); self.assertEqual(options['output_folder'], '')
        self.assertEqual(text.read_bytes(), before)
        self.assertFalse((self.root/'wrong-folder').exists())
        self.assertEqual(next(i for i in self.app.items if i.source==held).status, 'Queued')
        for output in jobs[0]['outputs']: self.assertGreater(len(PdfReader(output['path']).pages), 0)

    def test_additional_batches_arrive_while_worker_is_blocked(self):
        from puryf import engine
        entered = threading.Event(); release = threading.Event()
        original = engine.ConverterEngine.convert
        def slow(worker, source):
            if Path(source).name == 'first.txt':
                entered.set(); release.wait(5)
            return original(worker, source)
        first = self.source('first.txt'); second = self.source('second.txt'); held = self.source('held.txt')
        with patch.object(engine.ConverterEngine, 'convert', slow):
            self.send('convert', first)
            self.assertTrue(entered.wait(3))
            self.send('queue', held)
            self.send('convert', second)
            self.send('convert', first)  # active source must not be resubmitted
            self.assertEqual(len(self.app.service.list_jobs()), 2)
            self.assertEqual(next(i for i in self.app.items if i.source==held).status, 'Queued')
            release.set(); self.finish()
        self.assertEqual([j['status'] for j in self.app.service.list_jobs()], ['succeeded','succeeded'])
        self.assertEqual(next(i for i in self.app.items if i.source==held).status, 'Queued')

    def test_unsupported_missing_and_folders_are_logged_not_converted(self):
        self.send('convert', self.source('file.exe'), self.root/'gone.txt', self.root)
        self.assertEqual(self.app.service.list_jobs(), [])
        self.assertEqual(self.app.items, [])

    def test_pending_session_recovers_without_automatic_conversion(self):
        source = self.source(); self.send('queue', source)
        self.app.items[0].status = 'Pending'; self.app.save_session()
        self.app.items.clear(); self.app.tree.delete(*self.app.tree.get_children())
        self.app.load_session()
        self.assertEqual(self.app.items[0].status, 'Queued')
        self.assertFalse(self.app.service.busy)

    def test_mailbox_drains_on_tk_and_closing_leaves_requests_pending(self):
        inbox = Inbox(self.root/'ipc'); source = self.source()
        path = inbox.publish('queue', [source]); self.app.attach_explorer(inbox)
        deadline = time.monotonic()+2
        while path.exists() and time.monotonic()<deadline: self.app.update(); time.sleep(.01)
        self.assertFalse(path.exists()); self.assertEqual(len(self.app.items), 1)
        path = inbox.publish('queue', [self.source('later.txt')])
        self.app.after_cancel(self.app._explorer_after)
        self.app._closing = True; self.app._poll_explorer()
        self.assertTrue(path.exists())

    def test_missing_office_dependency_does_not_block_valid_mixed_inputs(self):
        from puryf import engine
        office = self.source('document.docx'); text = self.source('good.txt')
        before = office.read_bytes()
        with patch.object(engine, 'office_available', return_value=False):
            self.send('convert', office, text)
            self.finish()
        job = self.app.service.list_jobs()[0]
        self.assertEqual(job['status'], 'partial')
        self.assertEqual(len(job['outputs']), 1)
        self.assertIn('dependency_missing', [error['code'] for error in job['errors']])
        self.assertEqual(office.read_bytes(), before)

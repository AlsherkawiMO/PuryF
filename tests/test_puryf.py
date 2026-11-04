"""Real local conversion and desktop interaction regression checks.

Run: python -m unittest discover -s tests -v
Linux GUI checks need a display, e.g. xvfb-run -a python -m unittest discover -s tests -v.
"""
import importlib.util
import gc
import os
import shutil
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from puryf import desktop as p
from puryf import engine as core
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter


def settings(folder):
    return dict(output_folder=str(folder), overwrite=False, merge_pdf=False,
                compress_pdf=False, password_pdf=False, pdf_password="", ocr_pdf=False,
                image_paper="Original size", excel_fit_width=False, ocr_language="eng",
                ppt_layout=p.PPT_LAYOUTS[0], ppt_date_mode=p.PPT_DATE_MODES[0], command_timeout=30)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.options = settings(self.out)
        self.messages = []
        self.engine = core.ConverterEngine(self.options, self.messages.append, lambda *x: None,
                                        lambda *x: None, threading.Event(), reports_dir=self.root / "Reports")

    def tearDown(self):
        self.engine.quit_all()
        self.tmp.cleanup()

    def test_text_unicode_and_long_line(self):
        src = self.root / "notes.txt"
        src.write_text("PuryF résumé — training notes\n" + "longword" * 2000, encoding="utf-8")
        out = self.engine.convert(src)
        pages = PdfReader(out).pages
        self.assertGreater(len(pages), 1)
        self.assertIn("résumé", pages[0].extract_text())

    def test_image_paper_sizes_and_multiframe(self):
        src = self.root / "frames.tiff"
        Image.new("RGB", (120, 80), "red").save(src, save_all=True, append_images=[Image.new("RGB", (120, 80), "blue")])
        for paper, width in [("Original size", 120), ("A4", 595.28), ("Letter", 612)]:
            self.options["image_paper"] = paper
            self.options["overwrite"] = True
            out = self.engine.convert(src)
            pages = PdfReader(out).pages
            self.assertEqual(len(pages), 2)
            self.assertAlmostEqual(float(pages[0].mediabox.width), width, delta=1)

    def test_pdf_copy_compression_encryption_original_safe(self):
        src = self.root / "source.pdf"
        w = PdfWriter(); w.add_blank_page(width=200, height=300); w.write(src)
        original = src.read_bytes()
        self.options.update(output_folder="", compress_pdf=True, password_pdf=True, pdf_password="sample-password")
        out = self.engine.convert(src)
        self.assertNotEqual(src, out)
        self.assertEqual(src.read_bytes(), original)
        r = PdfReader(out)
        self.assertTrue(r.is_encrypted)
        self.assertTrue(r.decrypt("sample-password"))
        self.assertEqual(len(r.pages), 1)

    def test_existing_output_and_batch_collisions(self):
        src = self.root / "same.txt"; src.write_text("Text")
        image = self.root / "same.png"; Image.new("RGB", (50, 50), "white").save(image)
        first = self.engine.convert(src)
        second = self.engine.convert(image)
        self.assertNotEqual(first, second)
        another = core.ConverterEngine(self.options, lambda *x: None, lambda *x: None, lambda *x: None, threading.Event())
        with self.assertRaises(FileExistsError):
            another.convert(src)

    def test_email_html_and_attachment_names(self):
        from email.message import EmailMessage
        m = EmailMessage(); m['From'] = 'trainer@example.test'; m['To'] = 'learner@example.test'; m['Subject'] = 'Course'
        m.set_content('<p>Hello learner</p><script>hidden-script</script>', subtype='html')
        m.add_attachment(b'test', maintype='application', subtype='octet-stream', filename='lesson.txt')
        src = self.root / 'mail.eml'; src.write_bytes(m.as_bytes())
        text = '\n'.join(page.extract_text() for page in PdfReader(self.engine.convert(src)).pages)
        self.assertIn('Hello learner', text)
        self.assertIn('lesson.txt', text)
        self.assertNotIn('hidden-script', text)

    def test_batch_merge_report_and_status(self):
        self.options['merge_pdf'] = True
        items = []
        for i in range(2):
            src = self.root / f'file{i}.txt'; src.write_text(f'Lesson {i}')
            items.append(p.QueueItem(src))
        with patch.object(core, 'REPORTS_DIR', self.root / 'Reports'):
            self.engine.run_queue(list(enumerate(items)))
        self.assertEqual([x.status for x in items], ['Success', 'Success'])
        merged = list(self.out.glob('Merged*.pdf'))
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(PdfReader(merged[0]).pages), 2)
        self.assertEqual(len(list((self.root / 'Reports').glob('*.csv'))), 1)

    def test_cancel_external_command(self):
        errors = []
        def run():
            try: self.engine.run_command([sys.executable, '-c', 'import time; time.sleep(20)'])
            except Exception as e: errors.append(e)
        t = threading.Thread(target=run); t.start()
        time.sleep(.2); self.engine.stop_event.set(); t.join(5)
        self.assertFalse(t.is_alive())
        self.assertIsInstance(errors[0], core.ConversionCancelled)

    def test_ranges_and_unavailable_format_prechecks(self):
        self.assertEqual(p.parse_page_ranges('1-3,5', 5), [0, 1, 2, 4])
        for value in ['0', '6', '3-1', 'x']:
            with self.assertRaises(ValueError): p.parse_page_ranges(value, 5)
        self.assertTrue(self.engine.requirements(Path('drawing.dwg')))
        self.assertTrue(self.engine.requirements(Path('site.url')))

    @unittest.skipUnless(shutil.which('ocrmypdf') and shutil.which('tesseract') and shutil.which('gs'), 'OCR external tools unavailable')
    def test_real_english_ocr(self):
        from PIL import ImageFont
        image = Image.new('RGB', (1800, 700), 'white')
        font_path = next((f for f in [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'arial.ttf', Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if f.is_file()), None)
        if font_path is None: self.skipTest('No suitable OCR fixture font')
        font = ImageFont.truetype(str(font_path), 76)
        ImageDraw.Draw(image).text((100, 200), 'PuryF training document', fill='black', font=font)
        src = self.root / 'scanned.png'; image.save(src)
        self.options.update(ocr_pdf=True, image_paper='A4')
        output = self.engine.convert(src)
        text = '\n'.join(page.extract_text() for page in PdfReader(output).pages)
        self.assertIn('training', text.lower())


GUI_AVAILABLE = bool(os.name == 'nt' or os.environ.get('DISPLAY') or sys.platform == 'darwin')


@unittest.skipUnless(GUI_AVAILABLE, 'No desktop display; run with Xvfb or on Windows')
class DesktopTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.patches = [patch.object(p, 'APP_DIR', self.root), patch.object(p, 'STATE_PATH', self.root / 'session.json'), patch.object(p, 'REPORTS_DIR', self.root / 'Reports')]
        for x in self.patches: x.start()
        self.app = p.App(); self.errors = []
        self.app.report_callback_exception = lambda *e: self.errors.append(e)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        for x in self.patches: x.stop()
        self.tmp.cleanup()
        self.assertFalse(self.errors, self.errors)

    def populate(self, n=4):
        for i in range(n):
            src = self.root / f'lesson{i}.txt'; src.write_text(f'Lesson {i}')
            self.app.add_paths([src])
        self.app.update()

    def finish_jobs(self):
        deadline = time.monotonic() + 15
        while self.app.is_running() and time.monotonic() < deadline:
            self.app.update(); time.sleep(.01)
        time.sleep(.15); self.app.update()
        self.assertFalse(self.app.is_running())

    def key(self, widget, sequence, **kw):
        widget.focus_force(); self.app.update()
        widget.event_generate(sequence, **kw); self.app.update()

    def test_navigation_theme_resizing_and_fixed_actions(self):
        self.populate()
        for theme in ['light', 'dark']:
            self.app.theme.set(theme); self.app.apply_theme()
            for size in ['900x620', '1200x880', '1500x1000']:
                self.app.geometry(size); self.app.update()
                for name in ['convert', 'tools', 'dependencies']:
                    self.app.show_page(name); self.app.update()
                    self.assertTrue(self.app.start_button.winfo_ismapped())
                    self.assertLessEqual(self.app.start_button.winfo_rooty() + self.app.start_button.winfo_height(), self.app.winfo_rooty() + self.app.winfo_height())
                    self.assertLessEqual(self.app.start_button.winfo_rootx() + self.app.start_button.winfo_width(), self.app.winfo_rootx() + self.app.winfo_width())
        self.assertTrue(self.app.logo_light)
        self.assertTrue(self.app.logo_dark)

    def test_queue_shortcuts_and_entry_focus(self):
        self.populate()
        t = self.app.tree
        self.key(t, '<Control-a>'); self.assertEqual(len(t.selection()), 4)
        self.key(t, '<Control-d>'); self.assertEqual(len(self.app.items), 8)
        self.key(t, '<Control-i>'); self.assertEqual(len(t.selection()), 4)
        self.key(t, '<Delete>'); self.assertEqual(len(self.app.items), 4)
        t.selection_set(self.app.items[-1].uid)
        self.key(t, '<Control-Shift-Up>'); self.assertEqual(self.app.items[0].source.name, 'lesson3.txt')
        self.app.advanced_visible.set(True); self.app.toggle_advanced(); self.app.update()
        count = len(self.app.items)
        self.key(self.app.password_entry, '<Control-d>')
        self.assertEqual(len(self.app.items), count)
        self.app.log_visible.set(True); self.app.toggle_log(); self.app.update()
        self.app.log_text.insert('end', 'Test activity log')
        saved = self.root / 'log.txt'
        with patch.object(p.filedialog, 'asksaveasfilename', return_value=str(saved)):
            self.key(self.app.log_text, '<Control-s>')
        self.assertIn('Test activity log', saved.read_text())
        self.key(self.app.log_text, '<Control-l>')
        self.assertEqual(self.app.log_text.get('1.0', 'end').strip(), '')

    def test_scrolling_precision_queue_log_and_canvas(self):
        self.populate(80)
        t = self.app.tree
        t.yview_moveto(0); self.app.update()
        for _ in range(10): self.key(t, '<MouseWheel>', delta=-30)
        self.assertGreater(t.yview()[0], 0)
        self.app.advanced_visible.set(True); self.app.toggle_advanced()
        self.app.log_visible.set(True); self.app.toggle_log()
        self.app.geometry('900x620'); self.app.update()
        self.app.body_canvas.yview_moveto(0)
        label = self.app.drop_label
        for _ in range(6): self.key(label, '<MouseWheel>', delta=-30)
        self.assertGreater(self.app.body_canvas.yview()[0], 0)
        self.app.log_text.insert('end', '\n'.join('Log line '+str(i) for i in range(150)))
        self.app.log_text.yview_moveto(0); self.app.update()
        for _ in range(10): self.key(self.app.log_text, '<MouseWheel>', delta=-30)
        self.assertGreater(self.app.log_text.yview()[0], 0)
        t.xview_moveto(0); self.app.update()
        for _ in range(12): self.key(t, '<Shift-MouseWheel>', delta=-120)
        self.assertGreater(t.xview()[0], 0)
        self.assertEqual(self.app._touchpad_deltas((2 << 16) | 65533), (2, -3))

    def test_f5_real_worker_and_f8(self):
        self.populate(2)
        self.app.output_folder.set(str(self.root / 'out'))
        self.key(self.app.tree, '<F5>')
        deadline = time.monotonic() + 10
        while self.app.is_running() and time.monotonic() < deadline:
            self.app.update(); time.sleep(.01)
        time.sleep(.15); self.app.update()
        self.assertFalse(self.app.is_running())
        self.assertEqual([i.status for i in self.app.items], ['Success', 'Success'])
        self.assertEqual(len(list((self.root / 'out').glob('*.pdf'))), 2)
        self.key(self.app.tree, '<F8>'); self.assertTrue(self.app.stop_event.is_set())

    def test_session_without_passwords(self):
        self.populate(2)
        self.app.theme.set('dark'); self.app.password_pdf.set(True); self.app.pdf_password.set('never-save-this')
        self.app.save_session()
        text = p.STATE_PATH.read_text()
        self.assertNotIn('never-save-this', text)
        self.assertNotIn('pdf_password', text)
        self.assertIn('dark', text)

    def test_dark_default_and_saved_light_preference(self):
        self.assertEqual(self.app.theme.get(), 'dark')
        self.assertEqual(self.app.theme_button.cget('text'), 'Light theme')
        self.app.toggle_theme()
        self.assertEqual(self.app.theme.get(), 'light')
        self.app.save_session()
        self.app.destroy()
        self.app = p.App()
        self.app.report_callback_exception = lambda *e: self.errors.append(e)
        self.app.update()
        self.assertEqual(self.app.theme.get(), 'light')
        self.assertEqual(self.app.theme_button.cget('text'), 'Dark theme')

    def test_upgrade_defaults_to_dark_without_losing_queue(self):
        import json
        self.populate(1)
        self.app.save_session()
        data = json.loads(p.STATE_PATH.read_text())
        data['version'] = 1
        data['settings']['theme'] = 'light'
        p.STATE_PATH.write_text(json.dumps(data))
        self.app.destroy()
        self.app = p.App()
        self.app.report_callback_exception = lambda *e: self.errors.append(e)
        self.app.update()
        self.assertEqual(self.app.theme.get(), 'dark')
        self.assertEqual(len(self.app.items), 1)

    def test_zip_safety_and_state_locks(self):
        import zipfile
        good = self.root / 'good.zip'
        with zipfile.ZipFile(good, 'w') as z: z.writestr('folder/lesson.txt', 'Hello')
        self.app.add_paths([good]); self.assertEqual(len(self.app.items), 1)
        bad = self.root / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as z: z.writestr('../../escape.txt', 'unsafe')
        with self.assertRaises(RuntimeError): self.app.extract_zip_to_app(bad)
        self.app.set_running_state(True)
        self.assertIn('disabled', self.app.start_button.state())
        self.assertTrue(all('disabled' in w.state() for w in self.app.run_locked_widgets))
        self.app.set_running_state(False)
        self.assertNotIn('disabled', self.app.start_button.state())

    def test_shared_service_updates_desktop_without_gui_thread_callbacks(self):
        source = self.root / 'external.txt'; source.write_text('External adapter input')
        handle = self.app.service.submit_conversion([source], origin='api')
        self.finish_jobs()
        self.assertEqual(handle.snapshot()['status'], 'succeeded')
        self.assertEqual(len(self.app.items), 1)
        self.assertEqual(self.app.items[0].status, 'Success')
        self.assertEqual(self.app.tree.item(self.app.items[0].uid, 'values')[2], 'Success')

    def test_manual_merge_split_and_source_protection(self):
        sources = []
        for i in range(2):
            src = self.root / f'pdf{i}.pdf'
            w = PdfWriter(); w.add_blank_page(width=200+i, height=300); w.write(src); sources.append(str(src))
        merged = self.root / 'merged.pdf'
        with patch.object(p.filedialog, 'asksaveasfilename', return_value=str(merged)), patch.object(p.messagebox, 'showinfo'), patch.object(p.messagebox, 'showerror') as err:
            self.app.merge_selected_pdfs(sources)
            self.finish_jobs()
            err.assert_not_called()
        self.assertEqual(len(PdfReader(merged).pages), 2)
        part = self.root / 'part.pdf'
        with patch.object(p.filedialog, 'askopenfilename', return_value=str(merged)), patch.object(p.filedialog, 'asksaveasfilename', return_value=str(part)), patch.object(p.messagebox, 'askyesno', return_value=False), patch.object(p.simpledialog, 'askstring', return_value='2'), patch.object(p.messagebox, 'showinfo'), patch.object(p.messagebox, 'showerror') as err:
            self.app.split_pdf_dialog(); self.finish_jobs(); err.assert_not_called()
        self.assertEqual(float(PdfReader(part).pages[0].mediabox.width), 201)
        self.assertEqual(len(PdfReader(merged).pages), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)

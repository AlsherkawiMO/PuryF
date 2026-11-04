"""Actual Tk Studio edits, Arabic mirroring, preset and pause controls."""
import gc
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from pypdf import PdfWriter,PdfReader
from puryf import desktop
from puryf.studio import Studio

class V1DesktopTests(unittest.TestCase):
    def setUp(self):
        gc.collect();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch.object(desktop,'APP_DIR',self.root),patch.object(desktop,'STATE_PATH',self.root/'session.json'),patch.object(desktop,'REPORTS_DIR',self.root/'Reports')]
        for p in self.patches:p.start()
        self.app=desktop.App();self.errors=[];self.app.report_callback_exception=lambda *error:self.errors.append(error);self.app.update()
    def tearDown(self):
        self.app.destroy()
        for p in self.patches:p.stop()
        self.tmp.cleanup();self.assertFalse(self.errors,self.errors)
    def pdf(self):
        path=self.root/'source.pdf';writer=PdfWriter()
        for n in range(3):writer.add_blank_page(200+n,300)
        writer.write(path);return path
    def finish(self):
        deadline=time.monotonic()+8
        while self.app.service.busy and time.monotonic()<deadline:self.app.update();time.sleep(.01)
        self.app._process_job_events();self.app.update();self.assertFalse(self.app.service.busy)
    def studio_button(self):
        def find(widget):
            if widget.winfo_class()=='TButton' and str(widget.cget('text'))=='PDF Studio':return widget
            for child in widget.winfo_children():
                result=find(child)
                if result is not None:return result
        button=find(self.app);self.assertIsNotNone(button);return button
    def test_studio_navigation_opens_empty_without_file_dialog(self):
        with patch('puryf.workbench.filedialog.askopenfilenames') as picker:
            self.studio_button().invoke();self.app.update();picker.assert_not_called()
        windows=[w for w in self.app.winfo_children() if isinstance(w,Studio)]
        self.assertEqual(len(windows),1);self.assertFalse(windows[0].tree.get_children());windows[0].destroy()
    def test_studio_navigation_loads_one_and_multiple_selected_pdfs(self):
        source=self.pdf();other=self.root/'other.pdf';other.write_bytes(source.read_bytes())
        self.app.add_paths([source,other]);self.app.update()
        for count in (1,2):
            self.app.tree.selection_set([item.uid for item in self.app.items[:count]])
            self.studio_button().invoke();self.app.update()
            windows=[w for w in self.app.winfo_children() if isinstance(w,Studio)]
            self.assertEqual(len(windows),1);self.assertEqual(len(windows[0].paths),count)
            self.assertEqual(len(windows[0].tree.get_children()),3*count);windows[0].destroy()
    def test_studio_thumbnails_rotate_reorder_delete_and_save_selection(self):
        source=self.pdf();window=Studio(self.app,[source]);self.app.update()
        ids=window.tree.get_children();self.assertEqual(len(ids),3)
        window.tree.selection_set(ids[2]);window.move(-1);window.rotate();self.assertEqual(window.refs[ids[2]]['rotation'],90)
        output=self.root/'selected.pdf'
        with patch('puryf.studio.filedialog.asksaveasfilename',return_value=str(output)),patch.object(desktop.messagebox,'showinfo'),patch.object(desktop.messagebox,'showerror') as error:
            window.save(selected=True);self.finish();self.assertFalse(error.called)
        self.assertEqual(len(PdfReader(output).pages),1);self.assertEqual(PdfReader(output).pages[0].rotation,90)
        window.delete();self.assertEqual(len(window.tree.get_children()),2);window.undo_edit();self.assertEqual(len(window.tree.get_children()),3)
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:self.app.update();time.sleep(.01)
        self.assertTrue(window.images)
        window.destroy();self.app.update()
    def test_arabic_mirrors_and_restores_layout_without_reversing_paths(self):
        before=self.app.page_host.grid_info()['column'];columns=tuple(self.app.tree['displaycolumns'])
        self.app.toggle_language();self.app.update()
        self.assertEqual(self.app.language.get(),'ar');self.assertNotEqual(self.app.page_host.grid_info()['column'],before)
        self.assertEqual(tuple(self.app.tree['displaycolumns']),tuple(reversed(columns)))
        self.app.toggle_language();self.app.update();self.assertEqual(self.app.page_host.grid_info()['column'],before)
        self.assertEqual(tuple(self.app.tree['displaycolumns']),columns)
    def test_preset_and_pause_buttons_use_existing_service(self):
        self.app.preset_name.set('Small');self.app.apply_preset();self.assertTrue(self.app.compress_pdf.get());self.assertEqual(self.app.v1_options['image_max_edge'],1400)
        self.app.toggle_pause();self.assertTrue(self.app.service.paused)
        self.app.toggle_pause();self.assertFalse(self.app.service.paused)

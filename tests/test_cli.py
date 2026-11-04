"""Real subprocess CLI tests: outputs, request validation, signals and leases."""
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from puryf import cli
from puryf.explorer import InstanceLock
from pypdf import PdfReader, PdfWriter

class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=dict(os.environ,LOCALAPPDATA=str(self.root/'local'),PYTHONPATH=str(ROOT)+os.pathsep+os.environ.get('PYTHONPATH',''))

    def tearDown(self): self.tmp.cleanup()

    def text(self,name='notes.txt'):
        file=self.root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('PuryF CLI résumé\nTraining materials');return file

    def pdf(self,name='source.pdf',pages=4):
        file=self.root/name;writer=PdfWriter()
        for i in range(pages):writer.add_blank_page(width=200+i,height=300)
        writer.write(file);return file

    def call(self,*args,json_output=True,env=None):
        result=subprocess.run([sys.executable,'-m','puryf',*map(str,args),*(['--json'] if json_output else [])],
            cwd=ROOT,env=env or self.env,capture_output=True,text=True,timeout=20)
        if json_output:
            data=json.loads(result.stdout)
            self.assertEqual(data['exit_code'],result.returncode,result.stderr)
            return result,data
        return result

    def test_help_version_and_source_console_launcher(self):
        for args in [('--help',),('convert','--help'),('--version',)]:
            result=self.call(*args,json_output=False)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('PuryF' if args==('--version',) else 'usage:',result.stdout)
        source=self.text()
        result=subprocess.run([sys.executable,str(ROOT/'PuryF_CLI.py'),'convert',str(source),'--json'],cwd=self.root,env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(json.loads(result.stdout)['exit_code'],0,result.stderr)

    def test_headless_import_and_conversion_with_gui_blocked(self):
        source=self.text()
        script='''import sys,importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name.split('.')[0] in ('tkinter','tkinterdnd2'):raise ImportError('No GUI allowed')
sys.meta_path.insert(0,Block())
from puryf.cli import main
raise SystemExit(main(sys.argv[1:]))
'''
        result=subprocess.run([sys.executable,'-c',script,'convert',str(source),'--json'],cwd=ROOT,env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['result']['status'],'succeeded')

    def test_mixed_conversion_progress_json_and_safe_outputs(self):
        from PIL import Image
        source=self.text('عربي & notes.txt');before=source.read_bytes()
        image=self.root/'image.png';Image.new('RGB',(100,120),'orange').save(image)
        result=self.call('convert',source,image,'-o',self.root/'out',json_output=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('%',result.stderr);self.assertIn('2/2',result.stderr)
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(len(PdfReader(self.root/'out'/'عربي & notes.pdf').pages),1)
        result,data=self.call('convert',source,image,'-o',self.root/'other')
        self.assertEqual(result.returncode,0)
        self.assertEqual(data['result']['origin'],'cli');self.assertFalse(result.stderr)
        self.assertEqual(len(data['result']['outputs']),2)

    def test_recursive_folder_scan_dedup_and_output_subtree_exclusion(self):
        source=self.text('course/a.txt');nested=self.text('course/unit/b.txt')
        self.text('course/ignored.exe');self.text('course/out/already.txt')
        result,data=self.call('convert',source.parent,source,'-r','-o',source.parent/'out')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(data['scan']['count'],2);self.assertEqual(data['scan']['ignored'],1)
        self.assertEqual({Path(i['source']).name for i in data['result']['inputs']},{'a.txt','b.txt'})
        self.assertTrue((source.parent/'out/b.pdf').is_file())
        result,data=self.call('convert',source.parent,'-o',self.root/'flat')
        self.assertEqual(len(data['result']['inputs']),1)  # nonrecursive default

    def test_folder_symlink_is_not_followed(self):
        source=self.text('course/a.txt');other=self.text('other/b.txt')
        try:(source.parent/'linked').symlink_to(other.parent,target_is_directory=True)
        except OSError:self.skipTest('Symlinks unavailable')
        result,data=self.call('convert',source.parent,'-r','-o',self.root/'out')
        self.assertEqual(result.returncode,0)
        self.assertEqual(data['scan']['count'],1)

    def test_merge_and_both_split_modes_preserve_page_order_and_sources(self):
        a=self.pdf('a.pdf',3);b=self.pdf('b.pdf',2);before=a.read_bytes()
        merged=self.root/'merged.pdf'
        result,data=self.call('merge',a,b,'-o',merged)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(PdfReader(merged).pages),5)
        result,data=self.call('split',merged,'--pages','2-3,5','-o',self.root/'extract.pdf')
        self.assertEqual(result.returncode,0)
        self.assertEqual([float(p.mediabox.width) for p in PdfReader(self.root/'extract.pdf').pages],[201,202,201])
        result,data=self.call('split',merged,'--every','2','--output-dir',self.root/'parts')
        self.assertEqual(result.returncode,0)
        self.assertEqual([len(PdfReader(p['path']).pages) for p in data['result']['outputs']],[2,2,1])
        self.assertEqual(a.read_bytes(),before)
        result,data=self.call('merge',a,b,'-o',a,'--overwrite')
        self.assertNotEqual(result.returncode,0);self.assertEqual(a.read_bytes(),before)

    def test_request_file_relative_paths_large_list_and_utf8_bom(self):
        source=self.text('nested/فكرة & 100%!.txt')
        request=source.parent/'batch.json'
        request.write_text(json.dumps({'version':1,'command':'convert','inputs':[source.name]*3000,
                           'options':{'output_folder':'results'}},ensure_ascii=False),encoding='utf-8-sig')
        result,data=self.call('request',request)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(data['scan']['count'],1)
        self.assertTrue((source.parent/'results'/source.with_suffix('.pdf').name).is_file())

    def test_request_merge_split_and_strict_validation(self):
        source=self.pdf();request=self.root/'request.json'
        request.write_text(json.dumps({'version':1,'command':'split','inputs':[source.name],
                           'every':2,'output_dir':'parts'}))
        result,data=self.call('request',request);self.assertEqual(result.returncode,0)
        invalid=[{'version':1,'command':'split','inputs':[str(source)],'every':0,'output_dir':'parts'},
                 {'version':True,'command':'doctor'}, {'version':1,'command':{}},
                 {'version':1,'command':'convert','inputs':[str(source)],'shell':'anything'},
                 {'version':1,'command':'convert','inputs':[str(source)],'options':{'pdf_password':'never-echo'}},
                 {'version':1,'command':'convert','inputs':[str(source)],'recursive':'yes'}]
        for value in invalid:
            request.write_text(json.dumps(value))
            result,data=self.call('request',request)
            self.assertEqual(result.returncode,2)
            self.assertNotIn('never-echo',result.stdout)

    def test_doctor_and_dependency_exit_without_conversion(self):
        source=self.text();result,data=self.call('doctor',source)
        self.assertEqual(result.returncode,0);self.assertTrue(data['doctor']['ready'])
        self.assertFalse(source.with_suffix('.pdf').exists())
        result,data=self.call('doctor',self.root/'missing.docx')
        self.assertEqual(result.returncode,3);self.assertFalse(data['doctor']['ready'])
        self.assertTrue(data['doctor']['inputs'][0]['issues'])

    def test_failure_partial_skip_and_usage_exit_codes(self):
        source=self.text();missing=self.root/'missing.txt'
        result,data=self.call('convert',missing);self.assertEqual(result.returncode,1)
        result,data=self.call('convert',source,missing);self.assertEqual(result.returncode,4)
        result,data=self.call('convert',source);self.assertEqual(result.returncode,5)
        other=self.text('new.txt')
        result,data=self.call('convert',source,other);self.assertEqual(result.returncode,4)
        result,data=self.call('convert',source,'--overwrite');self.assertEqual(result.returncode,0)
        result,data=self.call('split',source,'--every','0','--output-dir',self.root/'parts');self.assertEqual(result.returncode,2)
        result,data=self.call('convert',source,'--timeout','0');self.assertEqual(result.returncode,2)
        result,data=self.call('request',self.root/'absent.json');self.assertEqual(result.returncode,2)

    def test_password_env_encrypts_and_is_not_exported(self):
        source=self.text();password='PuryF-secret-Only-In-Env'
        env=dict(self.env,PURYF_TEST_PASSWORD=password)
        result,data=self.call('convert',source,'--password-env','PURYF_TEST_PASSWORD',env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        reader=PdfReader(source.with_suffix('.pdf'));self.assertTrue(reader.is_encrypted)
        self.assertTrue(reader.decrypt(password));self.assertNotIn(password,result.stdout+result.stderr)
        self.assertNotIn('pdf_password',data['result']['options'])
        result,data=self.call('split',source.with_suffix('.pdf'),'--pages','1','-o',self.root/'part.pdf',
                              '--input-password-env','PURYF_TEST_PASSWORD',env=env)
        self.assertEqual(result.returncode,0)
        result,data=self.call('convert',source,'--password-env','PURYF_UNSET')
        self.assertEqual(result.returncode,2)

    def test_gui_launch_uses_desktop_entry_and_direct_argument_list(self):
        data={'command':'gui','inputs':[str(self.root/'notes & special.txt')],'convert':False}
        with patch.object(cli.subprocess,'Popen') as popen:
            popen.return_value.pid=123
            result=cli.gui(data)
        arguments=popen.call_args.args[0]
        self.assertTrue(arguments[1].endswith('PuryF.py'))
        self.assertEqual(arguments[-3:],['--explorer-queue','--',data['inputs'][0]])
        self.assertEqual(result['status'],'launch_requested')
        self.assertFalse(popen.call_args.kwargs.get('shell',False))

    def test_quiet_and_json_before_subcommand(self):
        source=self.text()
        result=self.call('convert',source,'--quiet',json_output=False)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout+result.stderr,'')
        result=self.call('--json','convert',self.text('second.txt'),json_output=False)
        self.assertEqual(json.loads(result.stdout)['exit_code'],0)

    @unittest.skipIf(os.name=='nt','POSIX signal delivery; Windows console Ctrl+C needs manual check')
    def test_sigint_cancels_waiting_job_with_json_and_exit_130(self):
        lease=InstanceLock(self.root/'local/PuryF/Conversion');self.assertTrue(lease.acquire())
        source=self.text()
        child=subprocess.Popen([sys.executable,'-m','puryf','convert',str(source),'--json'],cwd=ROOT,env=self.env,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            time.sleep(.8);child.send_signal(signal.SIGINT)
            stdout,stderr=child.communicate(timeout=8)
            self.assertEqual(child.returncode,130,stderr)
            result=json.loads(stdout);self.assertEqual(result['result']['status'],'cancelled')
            self.assertFalse(source.with_suffix('.pdf').exists())
        finally:
            lease.close()
            if child.poll() is None:child.kill();child.wait()

    def test_separate_process_waits_for_conversion_lease_and_releases_it(self):
        lease=InstanceLock(self.root/'local/PuryF/Conversion');self.assertTrue(lease.acquire())
        source=self.text()
        child=subprocess.Popen([sys.executable,'-m','puryf','convert',str(source),'--json'],cwd=ROOT,env=self.env,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            time.sleep(.8);self.assertIsNone(child.poll());self.assertFalse(source.with_suffix('.pdf').exists())
            lease.close()
            stdout,stderr=child.communicate(timeout=10)
            self.assertEqual(child.returncode,0,stderr);self.assertEqual(json.loads(stdout)['result']['status'],'succeeded')
            self.assertTrue(lease.acquire())
        finally:
            lease.close()
            if child.poll() is None:child.kill();child.wait()

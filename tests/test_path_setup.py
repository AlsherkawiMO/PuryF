"""Verify per-user PATH ownership without modifying the test machine's PATH."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

spec=importlib.util.spec_from_file_location('path_setup',Path(__file__).resolve().parents[1]/'installer/path_setup.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

class Key:
    def __init__(self,name):self.name=name
    def __enter__(self):return self
    def __exit__(self,*args):pass

class Registry:
    HKEY_CURRENT_USER=1;REG_SZ=1;REG_EXPAND_SZ=2
    def __init__(self,raw=None,kind=2):
        self.values={}
        if raw is not None:self.values[('Environment','Path')]=(raw,kind)
    def CreateKey(self,hive,name):return Key(name)
    def QueryValueEx(self,key,name):
        if (key.name,name) not in self.values:raise FileNotFoundError(name)
        return self.values[(key.name,name)]
    def SetValueEx(self,key,name,reserved,kind,value):self.values[(key.name,name)]=(value,kind)
    def DeleteValue(self,key,name):del self.values[(key.name,name)]

class PathSetupTests(unittest.TestCase):
    def test_raw_delimiters_survive_add_remove(self):
        for raw in ['C:\\Other;', ';C:\\Other;;', '']:
            changed,added=helper.add_entry(raw,'C:\\PuryF\\bin')
            self.assertTrue(added)
            self.assertEqual(helper.remove_entry(changed,'C:\\PuryF\\bin'),raw)

    def test_long_expandable_path_is_preserved_and_roundtrips(self):
        raw=r'%USERPROFILE%\tools;C:\Other App\bin;'+(';'.join(f'C:\\Tool{i}' for i in range(1000)))
        registry=Registry(raw);notify=Mock()
        with tempfile.TemporaryDirectory() as directory:
            helper.update('add',directory,registry,notify)
            after,kind=registry.values[('Environment','Path')]
            self.assertEqual(kind,2);self.assertTrue(after.startswith(raw+';'))
            helper.update('add',directory,registry,notify)
            self.assertEqual(registry.values[('Environment','Path')][0],after)
            # Simulate another app adding an unrelated entry after installation.
            registry.values[('Environment','Path')]=(after+';C:\\Later',2)
            helper.update('remove',directory,registry,notify)
            self.assertEqual(registry.values[('Environment','Path')],(raw+';C:\\Later',2))
            self.assertNotIn((helper.OWNER,'PathEntryOwned'),registry.values)
        self.assertEqual(notify.call_count,3)

    def test_preexisting_entry_is_not_owned_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            entry=str(Path(directory).resolve()/'bin')
            raw='C:\\Other;"'+entry+'"'
            registry=Registry(raw,1)
            helper.update('add',directory,registry,lambda:None)
            helper.update('remove',directory,registry,lambda:None)
            self.assertEqual(registry.values[('Environment','Path')],(raw,1))
            self.assertNotIn((helper.OWNER,'PathEntryOwned'),registry.values)

    def test_missing_path_can_be_added_and_cleaned(self):
        registry=Registry()
        with tempfile.TemporaryDirectory() as directory:
            helper.update('add',directory,registry,lambda:None)
            helper.update('remove',directory,registry,lambda:None)
        self.assertEqual(registry.values[('Environment','Path')],('',2))

    def test_unsupported_registry_value_is_untouched(self):
        registry=Registry('anything',99)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):helper.update('add',directory,registry,lambda:None)
        self.assertEqual(registry.values[('Environment','Path')],('anything',99))

    def test_other_install_location_cannot_remove_owned_entry(self):
        registry=Registry(r'C:\Other')
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            helper.update('add',a,registry,lambda:None);before=dict(registry.values)
            helper.update('remove',b,registry,lambda:None)
            self.assertEqual(registry.values,before)
            with self.assertRaises(RuntimeError):helper.update('add',b,registry,lambda:None)
            self.assertEqual(registry.values,before)

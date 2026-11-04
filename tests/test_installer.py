import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runtime_setup', Path(__file__).resolve().parents[1] / 'installer' / 'runtime_setup.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class InstallerSafetyTests(unittest.TestCase):
    def test_refuses_unmarked_directory_without_starting_install(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime.venv, 'EnvBuilder') as build:
            with self.assertRaisesRegex(RuntimeError, 'marker'):
                runtime.setup(directory)
            build.assert_not_called()

    def test_refuses_incomplete_payload(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime.venv, 'EnvBuilder') as build:
            root = Path(directory)
            (root / 'puryf-install.marker').write_text(runtime.MARKER)
            with self.assertRaisesRegex(RuntimeError, 'files are missing'):
                runtime.setup(root)
            build.assert_not_called()

    def test_refuses_linked_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime.venv, 'EnvBuilder') as build:
            root = Path(directory)
            (root / 'puryf-install.marker').write_text(runtime.MARKER)
            (root / 'PuryF.py').write_text('')
            (root / 'requirements.txt').write_text('')
            elsewhere = root / 'other'; elsewhere.mkdir()
            try:
                (root / '.venv').symlink_to(elsewhere, target_is_directory=True)
            except OSError:
                self.skipTest('Creating test symlinks is unavailable')
            with self.assertRaisesRegex(RuntimeError, 'link or junction'):
                runtime.setup(root)
            build.assert_not_called()

class ExplorerInstallGuardTests(unittest.TestCase):
    def load_guard(self):
        spec = importlib.util.spec_from_file_location('install_guard', Path(__file__).resolve().parents[1] / 'installer' / 'install_guard.py')
        guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
        return guard

    def test_guard_allows_first_install_without_lock_file(self):
        guard = self.load_guard()
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', LOCALAPPDATA=directory):
            self.assertEqual(guard.main(), 0)

    def test_guard_refuses_busy_desktop_and_allows_released_lock(self):
        import types
        from unittest.mock import Mock
        guard = self.load_guard()
        windows_lock = Mock()
        fake = types.SimpleNamespace(locking=windows_lock, LK_NBLCK=1, LK_UNLCK=2)
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', LOCALAPPDATA=directory), patch.dict('sys.modules', msvcrt=fake):
            path = Path(directory)/'PuryF/Explorer/instance.lock'
            path.parent.mkdir(parents=True); path.write_bytes(b'\0')
            windows_lock.side_effect = OSError('lock held')
            with patch('builtins.print'):
                self.assertEqual(guard.main(), 5)
            windows_lock.side_effect = None
            self.assertEqual(guard.main(), 0)
            self.assertEqual(windows_lock.call_args.args[1:], (2, 1))
            self.assertTrue(path.exists())  # never delete a live ownership file

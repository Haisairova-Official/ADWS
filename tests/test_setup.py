import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_setup as setup
from adws_i18n import tr as _tr


class SetupTests(unittest.TestCase):
    def test_build_environment_rejects_old_system_and_uses_rustup(self):
        import os, subprocess
        def version(command, **kwargs):
            modern = '/.cargo/bin/' in command[0]
            name = Path(command[0]).name
            return subprocess.CompletedProcess(command, 0, name + (' 1.87.0' if modern else ' 1.75.0'), '')
        def which(name, path=None):
            return ('/home/test/.cargo/bin/' if path.startswith('/home/test/.cargo/bin:') else '/usr/bin/') + name
        with patch.dict(os.environ, {'PATH':'/usr/bin', 'CARGO_HOME':'/home/test/.cargo'}), patch.object(setup.shutil, 'which', side_effect=which), patch.object(setup.subprocess, 'run', side_effect=version):
            self.assertTrue(setup.build_environment()['PATH'].startswith('/home/test/.cargo/bin:'))

    def test_build_environment_reports_missing_supported_toolchain(self):
        import subprocess
        with patch.object(setup.shutil, 'which', return_value='/bin/old'), patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'rustc 1.75.0','')):
            with self.assertRaisesRegex(RuntimeError, '1.87'):
                setup.build_environment()

    def test_decline_does_not_install(self):
        with patch.object(setup.shutil, 'which', return_value='/bin/tool'), patch.object(setup, 'confirm', return_value=False), patch.object(setup.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                setup.install_packages(['waybar'])
            run.assert_not_called()

    def test_install_requested_packages(self):
        with patch.object(setup.shutil, 'which', return_value='/bin/tool'), patch.object(setup, 'confirm', return_value=True), patch.object(setup.os, 'geteuid', return_value=0), patch.object(setup.subprocess, 'run') as run:
            setup.install_packages(['waybar', 'waybar'])
            run.assert_called_once_with(['apt-get', 'install', 'waybar'], check=True)

    def test_unsupported(self):
        with patch.object(setup.shutil, 'which', return_value=None), patch.object(setup.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                setup.install_packages(['waybar'])
            run.assert_not_called()

    def test_recheck_stops_on_failure(self):
        with patch.object(setup, 'ensure_waybar', return_value='/bin/tool'), patch.object(setup, 'dependency_errors', return_value=['missing']), patch.object(setup, 'install_packages'), patch.object(setup.shutil, 'which', return_value='/bin/tool'):
            with self.assertRaisesRegex(RuntimeError, _tr('补齐后仍有问题')):
                setup.prepare()

    def test_cancel(self):
        with patch.object(setup, 'prepare', side_effect=KeyboardInterrupt):
            self.assertEqual(setup.main(), 130)

    def test_atomic_library_install(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'source', Path(directory)/'target'
            source.write_bytes(b'new'); target.write_bytes(b'old')
            with target.open('rb') as old:
                setup.atomic_install(source, target)
                self.assertEqual(old.read(), b'old')
            self.assertEqual(target.read_bytes(), b'new')

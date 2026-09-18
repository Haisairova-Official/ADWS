import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import mnws_autostart as auto


class AutostartTests(unittest.TestCase):
    def test_enable_repeat_backup_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.kdl'
            path.write_text('// personal\n')
            auto.enable(path)
            first=path.read_text()
            auto.enable(path)
            self.assertEqual(first,path.read_text())
            self.assertIn('"-s"',first)
            self.assertEqual(path.with_suffix('.kdl.mnws-autostart-bak').read_text(),'// personal\n')
            self.assertEqual(auto.DESKTOP_PATTERN.sub('',auto.PATTERN.sub('',first)).strip(),'// personal')

    def test_existing_desktop_only_adds_taskbar(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.kdl'
            path.write_text(auto.DESKTOP_BEGIN+'\nspawn-at-startup "/old/start-desktop-layer"\n'+auto.DESKTOP_END+'\n')
            auto.enable(path)
            self.assertIn('"taskbar" "-s"',path.read_text())
            self.assertNotIn('/old/',path.read_text())
            self.assertEqual(path.read_text().count(auto.DESKTOP_BEGIN),1)

    def test_existing_taskbar_block_is_repaired_and_desktop_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.kdl'
            path.write_text(auto.BEGIN+'\nspawn-at-startup "/unmounted/MNWS/mnws" "taskbar" "-s"\n'+auto.END+'\n')
            auto.enable(path)
            self.assertNotIn('/unmounted/',path.read_text())
            self.assertTrue(auto.desktop_enabled(path.read_text()))
            auto.set_desktop(path,False)
            self.assertFalse(auto.desktop_enabled(path.read_text()))
            self.assertIn('"taskbar" "-s"',path.read_text())

    def test_disable_desktop_migrates_combined_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.kdl'
            path.write_text(auto.BEGIN+'\nspawn-at-startup "/old/mnws" "-s"\n'+auto.END+'\n')
            self.assertTrue(auto.desktop_enabled(path.read_text()))
            auto.set_desktop(path,False)
            self.assertFalse(auto.desktop_enabled(path.read_text()))
            self.assertIn('"taskbar" "-s"',path.read_text())

    def test_validation_failure_does_not_change_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.kdl';path.write_text('// unchanged\n')
            from unittest.mock import Mock
            with patch.object(auto.shutil,'which',return_value='/bin/niri'), patch.object(auto.subprocess,'run',return_value=Mock(returncode=1,stderr='invalid')):
                with self.assertRaises(ValueError):auto.enable(path)
            self.assertEqual(path.read_text(),'// unchanged\n')

    def test_decline_and_eof_do_not_write(self):
        for answer in ('n', EOFError()):
            with patch.object(auto,'ask',side_effect=[answer]), patch.object(auto,'enable') as enable:
                self.assertEqual(auto.main(),0)
                enable.assert_not_called()

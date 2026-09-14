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
            self.assertEqual(auto.PATTERN.sub('',first).strip(),'// personal')

    def test_existing_desktop_only_adds_taskbar(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.kdl'
            path.write_text('// ==== MNWS 桌面图标层自启（自动生成）====\n')
            auto.enable(path)
            self.assertIn('"taskbar" "-s"',path.read_text())

    def test_decline_and_eof_do_not_write(self):
        for answer in ('n', EOFError()):
            with patch.object(auto,'ask',side_effect=[answer]), patch.object(auto,'enable') as enable:
                self.assertEqual(auto.main(),0)
                enable.assert_not_called()

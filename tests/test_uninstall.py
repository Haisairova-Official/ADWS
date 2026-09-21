import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_uninstall as removal
from adws_i18n import tr as _tr


class UninstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='adws-uninstall-test-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / 'home'
        self.root = self.base / 'source'
        self.config = self.base / 'config'
        self.state = self.base / 'state'
        self.root.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(removal, 'ROOT', self.root).start()
        patch.dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.config), XDG_STATE_HOME=str(self.state)).start()
        self.control = patch('adws_runtime.main', return_value=0).start()
        (self.home / '.local/bin').mkdir(parents=True)
        (self.home / '.local/bin/adws').symlink_to(self.root / 'adws')
        self.bar = self.config / 'waybar'
        self.bar.mkdir(parents=True)
        (self.bar / 'config-bottom.jsonc').write_text('{}')
        (self.bar / 'style-bottom.css').write_text('/* mine */')
        (self.bar / 'modules.jsonc').write_text('shared modules')
        (self.bar / 'colors.css').write_text('shared colors')
        for relative in ('adws', 'niri-desktop-layer'):
            (self.config / relative).mkdir()
            (self.config / relative / 'preferences').write_text('keep me')
        desktop = self.home / 'Desktop'
        desktop.mkdir()
        (desktop / 'important.txt').write_text('user document')
        self.niri = self.config / 'niri/config.kdl'
        self.niri.parent.mkdir()
        self.niri.write_text('input {}\n// ==== ADWS 桌面图标层自启（自动生成）====\nspawn-at-startup "adws-desktop"\n// ==== ADWS 桌面图标层自启 END ====\n')
        self.lib = self.home / '.local/lib/waybar/libniri_taskbar.so'
        self.lib.parent.mkdir(parents=True)
        self.lib.write_bytes(b'ADWS test binary')
        removal.save_inventory({'root':str(self.root), 'configs':[str(self.bar / 'config-bottom.jsonc')],
                                'libraries':{'libniri_taskbar.so':removal.digest(self.lib)}})

    def run_answers(self, answers):
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers) as ask, redirect_stdout(output):
            result = removal.uninstall()
        return result, output.getvalue(), ask

    def test_default_and_eof_cancel_without_changes(self):
        for answers in ([''], ['n'], [EOFError()], ['y', EOFError()]):
            result, output, ask = self.run_answers(answers)
            self.assertEqual(result, 0)
            self.assertIn(_tr('已取消。'), output)
            self.assertTrue((self.home / '.local/bin/adws').is_symlink())
            self.assertTrue(self.lib.exists())
            self.control.assert_not_called()

    def test_default_keep_preserves_config_and_removes_integration(self):
        result, output, ask = self.run_answers(['y', ''])
        self.assertEqual(result, 0)
        self.assertEqual([call.args[0] for call in ask.call_args_list],
                         [_tr('您真的要卸载adws吗？（y/N）'), _tr('您需要保留配置文件便于以后使用吗？（Y/n）')])
        self.assertEqual(output, _tr('卸载中，感谢您的使用。\n'))
        self.assertFalse((self.home / '.local/bin/adws').is_symlink())
        self.assertFalse(self.lib.exists())
        self.assertTrue((self.bar / 'config-bottom.jsonc').exists())
        self.assertTrue((self.config / 'adws/preferences').exists())
        self.assertEqual(self.niri.read_text(), 'input {}\n')
        self.assertEqual(self.control.call_count, 2)

    def test_purge_removes_only_owned_config(self):
        result, _, _ = self.run_answers(['yes', 'n'])
        self.assertEqual(result, 0)
        self.assertFalse((self.bar / 'config-bottom.jsonc').exists())
        self.assertTrue((self.bar / 'style-bottom.css').exists(), 'unrecorded existing config must survive')
        self.assertFalse((self.config / 'adws').exists())
        self.assertTrue((self.bar / 'modules.jsonc').exists())
        self.assertTrue((self.bar / 'colors.css').exists())
        self.assertEqual((self.home / 'Desktop/important.txt').read_text(), 'user document')
        self.assertTrue(self.root.exists())

    def test_changed_library_and_foreign_link_survive(self):
        self.lib.write_bytes(b'other installation')
        command = self.home / '.local/bin/adws'
        command.unlink()
        command.symlink_to(self.base / 'another-adws')
        self.run_answers(['y', 'n'])
        self.assertTrue(self.lib.exists())
        self.assertEqual(command.readlink(), self.base / 'another-adws')

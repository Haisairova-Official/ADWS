import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_windows as windows


class WindowRulesTests(unittest.TestCase):
    def test_preserves_user_rules_and_is_idempotent(self):
        original = 'window-rule { match app-id="other-app"; open-floating false; }\n'
        result = windows.compose(original)
        self.assertIn(original, result)
        self.assertEqual(result, windows.compose(result))
        for app in ('adws-config', 'adws-layout', 'adws-clock', 'adws-setup'):
            self.assertIn('^'+app+'$', result)

    def test_install_preserves_symlink_and_backs_up(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'actual.kdl';target.write_text('// user settings\n')
            link = Path(temp)/'config.kdl';link.symlink_to(target)
            with patch('adws_autostart.shutil.which', return_value=None):
                self.assertTrue(windows.install(link))
            self.assertTrue(link.is_symlink())
            self.assertIn(windows.BEGIN, target.read_text())
            self.assertEqual(target.with_suffix('.kdl.adws-autostart-bak').read_text(), '// user settings\n')
            self.assertFalse(windows.install(Path(temp)/'missing.kdl'))

    def test_explicit_config_path(self):
        with patch.dict(os.environ, {'NIRI_CONFIG': '/tmp/custom-niri.kdl'}):
            self.assertEqual(windows.config_path(), Path('/tmp/custom-niri.kdl'))

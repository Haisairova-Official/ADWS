import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_launcher as launcher
import adws_layout as layout


class LauncherTests(unittest.TestCase):
    def test_layout_launcher_overrides_include_without_losing_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'apps.jsonc').write_text(json.dumps({'custom/applauncher': {
                'format': 'My Apps', 'on-click': 'old-launcher', 'tooltip': False}}))
            for command in ['fuzzel', 'rofi -show drun', 'my-launcher --theme "my theme"']:
                result = layout.render_waybar_config(
                    {'builtins': [], 'plugins': [], 'options': {'start_launcher_command': command}}, available=[],
                    base={'include': ['apps.jsonc']}, config_path=root / 'bar.jsonc')
                self.assertEqual(result['custom/applauncher'], {
                    'format': 'My Apps', 'on-click': command, 'tooltip': False})

    def test_layout_without_launcher_setting_keeps_existing_command(self):
        result = layout.render_waybar_config({'builtins': [], 'plugins': []}, available=[], base={
            'custom/applauncher': {'on-click': 'existing --custom'}})
        self.assertEqual(result['custom/applauncher']['on-click'], 'existing --custom')

    def test_layout_rejects_empty_launcher(self):
        with self.assertRaises(ValueError):
            layout.render_waybar_config({'options': {'start_launcher_command': '  '}},
                                        available=[], base={})

    def test_priority(self):
        with patch.object(launcher.shutil, 'which', return_value='/bin/present'):
            self.assertEqual(launcher.select_launcher(), 'fuzzel')

    def test_rofi(self):
        with patch.object(launcher.shutil, 'which', side_effect=lambda name: '/bin/rofi' if name == 'rofi' else None):
            self.assertEqual(launcher.select_launcher(), 'rofi -show drun')

    def test_custom_and_empty(self):
        with patch.object(launcher.shutil, 'which', return_value=None), patch.object(launcher, 'ask', side_effect=['n', '', 'my-launcher --apps']):
            self.assertEqual(launcher.select_launcher(), 'my-launcher --apps')

    def test_cancel(self):
        with patch.object(launcher.shutil, 'which', return_value=None), patch.object(launcher, 'ask', side_effect=EOFError):
            with self.assertRaises(EOFError):
                launcher.select_launcher()

    def test_default_install(self):
        installed = False
        def which(name):
            return '/usr/bin/' + name if name == 'apt-get' or (name == 'fuzzel' and installed) else None
        def run(*args, **kwargs):
            nonlocal installed
            installed = True
            return Mock(returncode=0)
        with patch.object(launcher.shutil, 'which', side_effect=which), patch.object(launcher, 'ask', return_value=''), patch.object(launcher.os, 'geteuid', return_value=0), patch.object(launcher.subprocess, 'run', side_effect=run) as execute:
            self.assertEqual(launcher.select_launcher(), 'fuzzel')
            self.assertEqual(execute.call_args.args[0], ['/usr/bin/apt-get', 'install', 'fuzzel'])

    def test_install_failure(self):
        with patch.object(launcher.shutil, 'which', side_effect=lambda name: '/bin/apt-get' if name == 'apt-get' else None), patch.object(launcher, 'ask', return_value='y'), patch.object(launcher.os, 'geteuid', return_value=0), patch.object(launcher.subprocess, 'run', return_value=Mock(returncode=1)):
            with self.assertRaises(RuntimeError):
                launcher.select_launcher()

    def test_config_preserves_values_link_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'shared.jsonc'
            original = '{// comment\n"clock":{"format":"test"},"custom/applauncher":{"format":"Apps","on-click":"old"}}'
            target.write_text(original)
            link = Path(directory) / 'modules.jsonc'
            link.symlink_to(target)
            launcher.configure(link, 'fuzzel')
            self.assertTrue(link.is_symlink())
            data = json.loads(target.read_text())
            self.assertEqual(data['clock']['format'], 'test')
            self.assertEqual(data['custom/applauncher']['on-click'], 'fuzzel')
            self.assertEqual(target.with_name(target.name + '.adws-launcher.bak').read_text(), original)

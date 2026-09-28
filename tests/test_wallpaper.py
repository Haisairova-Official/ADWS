import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_wallpaper as wallpaper


class WallpaperTests(unittest.TestCase):
    def test_conflicting_service_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CONFIG_HOME': temp}), patch.object(wallpaper, 'validate', return_value='/picture.png'), patch.object(wallpaper, 'running', return_value={123: 'hyprpaper'}), patch.object(wallpaper.subprocess, 'run') as run, patch.object(wallpaper.os, 'kill') as kill:
            with self.assertRaises(ValueError): wallpaper.apply('awww', '/picture.png')
            run.assert_not_called()
            kill.assert_not_called()

    def test_failed_application_keeps_existing_service(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CONFIG_HOME': temp}), patch.object(wallpaper, 'validate', return_value='/picture with spaces.png'), patch.object(wallpaper, 'running', return_value={123: 'hyprpaper'}), patch.object(wallpaper.subprocess, 'run', side_effect=[Mock(returncode=0), Mock(returncode=1, stderr='failure')]) as run, patch.object(wallpaper.os, 'kill') as kill:
            with self.assertRaises(RuntimeError): wallpaper.apply('awww', '/picture with spaces.png', {123: 'hyprpaper'})
            self.assertEqual(run.call_args.args[0], ['awww', 'img', '/picture with spaces.png'])
            kill.assert_not_called()

    def test_restore_does_not_replace_running_wallpaper(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CONFIG_HOME': temp}), patch.object(wallpaper, 'running', return_value={123: 'swaybg'}), patch.object(wallpaper, 'apply') as apply:
            wallpaper.config_path().parent.mkdir(parents=True)
            wallpaper.config_path().write_text('{"engine":"awww","image":"/picture.png"}')
            wallpaper.restore()
            apply.assert_not_called()

    def test_install_uses_graphical_authorization(self):
        with patch.object(wallpaper.shutil, 'which', side_effect=lambda name: '/usr/bin/'+name if name in ('apt-get', 'pkexec') else None), patch.object(wallpaper.os, 'geteuid', return_value=1000):
            self.assertEqual(wallpaper.install_command(), ['pkexec', 'apt-get', 'install', '-y', 'awww'])

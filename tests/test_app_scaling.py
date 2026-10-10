import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_app_scaling as scaling
from gi.repository import Gio

class ScalingTests(unittest.TestCase):
    def test_field_codes_and_quoted_executable(self):
        command = scaling.scaling_command('"/opt/My App/browser" --new-window %U', 1.7, 'electron')
        self.assertEqual(command, '"/opt/My App/browser" --new-window --force-device-scale-factor=1.7 %U')
        self.assertEqual(command.count('%U'), 1)

    def test_reject_invalid_scale(self):
        for value in (float('nan'), float('inf'), 0, 5):
            with self.assertRaises(ValueError): scaling.scaling_command('/bin/app %F', value, 'qt')

    def test_save_restore_preserves_actions_and_other_edits(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_DATA_HOME': directory}):
            path = Path(directory)/'applications/test.desktop'; path.parent.mkdir()
            original = '[Desktop Entry]\nType=Application\nName=Test\nExec=/bin/true %F\nActions=new;\n\n[Desktop Action new]\nName=New\nExec=/bin/true --new %U\n'
            path.write_text(original)
            app = Gio.DesktopAppInfo.new_from_filename(str(path))
            scaling.save(app, 1.7, 'qt'); scaling.save(app, 2, 'qt')
            data = scaling.key_file(path)
            self.assertEqual(data.get_string('Desktop Entry','Exec').count('QT_SCALE_FACTOR='), 1)
            self.assertIn('QT_SCALE_FACTOR=2', data.get_string('Desktop Action new','Exec'))
            path.write_text(path.read_text().replace('Name=Test','Name=Edited'))
            scaling.restore(app)
            data = scaling.key_file(path)
            self.assertEqual(data.get_string('Desktop Entry','Name'), 'Edited')
            self.assertEqual(data.get_string('Desktop Entry','Exec'), '/bin/true %F')
            self.assertEqual(data.get_string('Desktop Action new','Exec'), '/bin/true --new %U')

    def test_symlink_not_modified(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_DATA_HOME': directory}):
            source=Path(directory)/'source.desktop'; source.write_text('[Desktop Entry]\nType=Application\nName=Test\nExec=/bin/true\n')
            dest=Path(directory)/'applications/test.desktop';dest.parent.mkdir();dest.symlink_to(source)
            app=Gio.DesktopAppInfo.new_from_filename(str(dest))
            with self.assertRaises(ValueError): scaling.save(app, 1.7, 'qt')

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_commands as commands


class CommandTests(unittest.TestCase):
    def test_zsh_login_path_persists_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            profile = home / '.profile'
            profile.write_text('export EXISTING_SETTING=1\n')
            with patch.dict(os.environ, {'HOME': directory, 'SHELL': '/bin/zsh', 'ZDOTDIR': directory}):
                commands.persist_user_path()
                commands.persist_user_path()
                result = __import__('subprocess').run(
                    ['/bin/sh', '-c', '. "$HOME/.zprofile"; . "$HOME/.zprofile"; printf "%s" "$PATH"'],
                    env={**os.environ, 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.split(':').count(str(home / '.local/bin')), 1)
            self.assertIn('export EXISTING_SETTING=1', profile.read_text())
            self.assertEqual(profile.read_text().count('# >>> ADWS'), 1)
            self.assertEqual((home / '.profile.adws-path.bak').read_text(), 'export EXISTING_SETTING=1\n')

    def test_link_and_repeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            directory = home / '.local/bin'
            with patch.dict(os.environ, {'HOME': temporary, 'PATH':str(directory)+os.pathsep+os.environ['PATH']}), patch.object(commands, 'read_inventory', return_value={}), patch.object(commands, 'save_inventory'):
                commands.install()
                commands.install()
            self.assertEqual((directory/'adws').resolve(), commands.ROOT/'adws')

    def test_foreign_command_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)/'.local/bin'
            directory.mkdir(parents=True)
            (directory/'adws').write_text('foreign')
            with patch.dict(os.environ, {'HOME':temporary, 'PATH':str(directory)}), patch.object(commands, 'read_inventory', return_value={}):
                with self.assertRaises(RuntimeError):
                    commands.install()
            self.assertEqual((directory/'adws').read_text(), 'foreign')

    def test_decline_system_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.dict(os.environ, {'PATH':str(directory)}), patch.object(commands, 'SYSTEM_BIN', directory), patch.object(commands, 'ask', return_value='n'), patch.object(commands, 'run') as run:
                with self.assertRaises(RuntimeError):
                    commands.install()
                run.assert_not_called()

    def test_sudo_when_required(self):
        with patch.object(commands.os, 'access', return_value=False), patch.object(commands.shutil, 'which', return_value='/usr/bin/sudo'), patch.object(commands.subprocess, 'run') as run:
            commands.run(['ln', '-s', '/source', '/usr/local/bin/adws'], Path('/usr/local/bin'))
            run.assert_called_once_with(['sudo', 'ln', '-s', '/source', '/usr/local/bin/adws'], check=True)

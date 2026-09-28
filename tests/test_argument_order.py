import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_runtime as runtime


class ArgumentOrderTests(unittest.TestCase):
    def test_reversed_start(self):
        with patch.object(runtime, 'pids', return_value=[123]) as pids:
            self.assertEqual(runtime.main(['-s', 'taskbar']), 0)
            pids.assert_called_once_with('taskbar')

    def test_global_start_both(self):
        with patch.object(runtime, 'pids', return_value=[123]) as pids:
            self.assertEqual(runtime.main(['-s']), 0)
            self.assertEqual([call.args[0] for call in pids.call_args_list], ['desktop', 'taskbar'])

    def test_invalid_global_arguments_no_actions(self):
        for args in (['-s', '-S'], ['-s', 'wrong'], ['-s', '-6'], ['-d']):
            with patch.object(runtime, 'pids') as pids:
                with self.assertRaises(SystemExit):
                    runtime.main(args)
                pids.assert_not_called()

    def test_shell_dispatch_preserves_order(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory)/'python3'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            python.chmod(0o755)
            for args in (['-s'], ['-s','desktop'], ['-6','taskbar','-d']):
                result = subprocess.run(['bash', str(root/'adws'), *args], env={**os.environ,'PATH':directory+os.pathsep+os.environ['PATH']}, capture_output=True,text=True)
                self.assertEqual(result.returncode,0)
                self.assertEqual(result.stdout.splitlines()[1:],args)

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_plugin_runner as runner


class RunnerSelectionTests(unittest.TestCase):
    def test_auto_without_binary_falls_back(self):
        with patch.dict(os.environ, {'ADWS_PLUGIN_RUNNER': 'auto'}), patch.object(Path, 'is_file', return_value=False), patch.object(runner, 'execute', return_value=0) as fallback:
            self.assertEqual(runner.dispatch(Path('/unused'), {'id': 'test', 'entry': 'main.py'}, {}), 0)
            fallback.assert_called_once()

    def test_explicit_rust_missing_does_not_silently_fallback(self):
        with patch.dict(os.environ, {'ADWS_PLUGIN_RUNNER': 'rust'}), patch.object(Path, 'is_file', return_value=False), patch.object(runner, 'execute') as fallback:
            with self.assertRaises(ValueError): runner.dispatch(Path('/unused'), {'id': 'test', 'entry': 'main.py'}, {})
            fallback.assert_not_called()

    def test_explicit_python_preserves_fallback(self):
        with patch.dict(os.environ, {'ADWS_PLUGIN_RUNNER': 'python'}), patch.object(runner, 'execute', return_value=0) as fallback:
            self.assertEqual(runner.dispatch(Path('/unused'), {}, {}), 0)
            fallback.assert_called_once()

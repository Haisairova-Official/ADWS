import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_taskbar_recover as recovery


class RecoveryTests(unittest.TestCase):
    def test_rejects_unrelated_or_stale_process(self):
        with patch.object(recovery.os, 'getppid', return_value=123):
            with self.assertRaises(ValueError):
                recovery.recover(456)
        with self.assertRaises(ValueError):
            recovery.configuration(['waybar', '-c', '/tmp/config-top.jsonc', '-s', '/tmp/top.css'])

    def test_preserves_exact_configuration_and_style(self):
        self.assertEqual(recovery.configuration(['waybar', '--config=/a b/config-bottom.jsonc', '--style=/a b/style.css']),
                         (Path('/a b/config-bottom.jsonc'), Path('/a b/style.css')))
        with self.assertRaises(ValueError):
            recovery.configuration(['waybar', '-c', '/a/config-bottom.jsonc'])

    def test_rate_limit_survives_restart_and_expires(self):
        self.assertEqual(recovery.recent_attempts([100, 650, 900], 1000), [650, 900])
        self.assertEqual(recovery.recent_attempts([650, 900], 1600), [])
        # A small clock correction must not bypass the limit.
        self.assertEqual(recovery.recent_attempts([1050], 1000), [1050])
        for malformed in ({}, ['bad'], [True]):
            with self.assertRaises(ValueError):
                recovery.recent_attempts(malformed, 1000)


if __name__ == '__main__':
    unittest.main()

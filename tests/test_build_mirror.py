import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_setup as setup
class MirrorTests(unittest.TestCase):
    def test_non_chinese_never_prompts(self):
        with patch('adws_i18n.chinese',return_value=False), patch.object(setup,'confirm') as ask:
            self.assertEqual(setup.choose_build_mirror({})['ADWS_BUILD_MIRROR'],'0');ask.assert_not_called()
    def test_chinese_prompts_once(self):
        with patch('adws_i18n.chinese',return_value=True), patch.object(setup,'confirm',return_value=True) as ask:
            env=setup.choose_build_mirror({});self.assertEqual(env['ADWS_BUILD_MIRROR'],'1')
            self.assertEqual(setup.choose_build_mirror(env),env);ask.assert_called_once()
            self.assertIn('source.crates-io.replace-with="adws-rsproxy"',setup.cargo_build_command(env))
    def test_decline_uses_default(self):
        with patch('adws_i18n.chinese',return_value=True), patch.object(setup,'confirm',return_value=False):
            self.assertEqual(setup.cargo_build_command(setup.choose_build_mirror({})),['cargo','build','--release','--locked'])

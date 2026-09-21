import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from adws_i18n import chinese, tr
from desktop_layer.i18n import catalogue
import adws_runtime


class LanguageTests(unittest.TestCase):
    def test_locale_precedence_and_english_fallback(self):
        cases = [({}, False), ({'LANG': 'zh_CN.UTF-8'}, True),
                 ({'LANG': 'zh_TW.UTF-8'}, True), ({'LANG': 'de_DE.UTF-8'}, False),
                 ({'LANG': 'zh_CN.UTF-8', 'LC_MESSAGES': 'en_US.UTF-8'}, False),
                 ({'LANG': 'en_US.UTF-8', 'LANGUAGE': 'zh_CN:en'}, True),
                 ({'LC_ALL': 'C.UTF-8', 'LANGUAGE': 'zh_CN'}, False)]
        for env, expected in cases:
            with self.subTest(env=env):
                self.assertEqual(chinese(env), expected)
                run = subprocess.run(['bash', '-c', 'source "$1"; adws_message zh en', '_', str(ROOT/'scripts/adws-i18n.sh')], env={**env, 'PATH': os.defpath}, capture_output=True, text=True, check=True)
                self.assertEqual(run.stdout.strip(), 'zh' if expected else 'en')

    def test_help_in_both_languages(self):
        for locale, word in [('zh_CN.UTF-8', '最新更新'), ('en_US.UTF-8', 'Latest updates'), ('fr_FR.UTF-8', 'Latest updates')]:
            with patch.dict(os.environ, {'LC_ALL': locale, 'LANGUAGE': ''}):
                output = adws_runtime.help_text()
                self.assertIn(word, output)
                if not chinese():
                    self.assertFalse(re.search(r'[\u4e00-\u9fff]', output))

    def test_translation_coverage_and_python311(self):
        messages = catalogue()
        for folder in ('tools', 'src/niri-desktop-layer/desktop_layer'):
            for path in (ROOT / folder).glob('*.py'):
                tree = ast.parse(path.read_text(), feature_version=(3,11))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_tr' and node.args and isinstance(node.args[0], ast.Constant):
                        value = node.args[0].value
                        self.assertIn(value, messages, (path.name, value))
                        self.assertFalse(re.search(r'[\u4e00-\u9fff]', messages[value]), (path.name, value))
        for text in json.loads((ROOT/'build-info.json').read_text())['changes']:
            self.assertIn(text, messages)

    def test_user_text_is_not_rewritten(self):
        with patch.dict(os.environ, {'LC_ALL':'en_US.UTF-8', 'LANGUAGE':''}):
            filename = '桌面图标-我的照片.png'
            self.assertEqual(tr('打开失败 %s: %s') % (filename, 'detail'), 'Failed to open 桌面图标-我的照片.png: detail')

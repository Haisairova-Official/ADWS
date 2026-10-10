"""Exercise the public shell entry, rather than importing the window directly."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class SidebarEntryTests(unittest.TestCase):
    def test_normal_click_and_help_dispatch_to_sidebar(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir();(root/'bin').mkdir()
            shutil.copy2(ROOT/'adws',root/'adws')
            shutil.copy2(ROOT/'scripts/adws-i18n.sh',root/'scripts/adws-i18n.sh')
            python=root/'bin/python3';python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n');python.chmod(0o755)
            env={**os.environ,'PATH':str(root/'bin')+':'+os.environ['PATH']}
            for args in (['sidebar'],['sidebar','--help']):
                result=subprocess.run(['bash',str(root/'adws'),*args],capture_output=True,text=True,env=env,check=True)
                lines=result.stdout.splitlines()
                self.assertEqual(lines[0],str(root/'tools/adws_sidebar.py'))
                self.assertEqual(lines[1:],args[1:])

    def test_real_sidebar_help_starts_in_fresh_process(self):
        result=subprocess.run(['bash',str(ROOT/'adws'),'sidebar','--help'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('ADWS dashboard sidebar',result.stdout)


class SidebarLocaleTests(unittest.TestCase):
    def test_warm_chinese_caller_replaces_stale_c_locale(self):
        from unittest.mock import patch
        import sys
        sys.path.insert(0,str(ROOT/'tools'))
        from adws_sidebar import apply_request_locale, chinese
        with patch.dict(os.environ, {'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','LANGUAGE':'en'}, clear=True):
            self.assertTrue(apply_request_locale({'LANG':'zh_CN.UTF-8'}))
            self.assertTrue(chinese())
            self.assertNotIn('LC_ALL',os.environ)
            self.assertNotIn('LANGUAGE',os.environ)
            self.assertFalse(apply_request_locale({'LANG':'zh_CN.UTF-8'}))
            self.assertFalse(apply_request_locale({'PATH':'/untrusted'}))
            self.assertTrue(chinese())

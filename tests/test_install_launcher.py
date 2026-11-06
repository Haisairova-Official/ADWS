import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_launcher as launcher

class ManagedLauncherTests(unittest.TestCase):
    def test_custom_launcher_and_module_remain_byte_identical_on_integrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp);layout=config/'adws/taskbar-layout.json';layout.parent.mkdir()
            modules=config/'waybar/modules.jsonc';modules.parent.mkdir()
            a=json.dumps({'options':{'start_launcher_mode':'custom','start_launcher_command':'my-personal-launcher'}})
            b='// personal comment\n{"custom/applauncher":{"on-click":"my-personal-launcher"}}'
            layout.write_text(a);modules.write_text(b)
            plan={'config_home':str(config),'launcher_plan':launcher.installation_plan(config)}
            with patch('adws_install_workflow.approved_plan',return_value=plan),patch.object(launcher,'save_selection') as save:
                launcher.apply_install_plan();save.assert_not_called()
            self.assertEqual(layout.read_text(),a);self.assertEqual(modules.read_text(),b)

    def test_first_install_initializes_only_after_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp);plan={'config_home':str(config),'launcher_plan':launcher.installation_plan(config)}
            modules=config/'waybar/modules.jsonc';modules.parent.mkdir();modules.write_text('{}')
            with patch('adws_install_workflow.approved_plan',return_value=plan),patch.object(launcher,'save_selection') as save:
                launcher.apply_install_plan();save.assert_called_once_with(launcher.native_menu_command())
            self.assertEqual(json.loads(modules.read_text())['custom/applauncher']['on-click'],launcher.native_menu_command())

    def test_concurrent_user_selection_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp);plan={'config_home':str(config),'launcher_plan':launcher.installation_plan(config)}
            layout=config/'adws/taskbar-layout.json';layout.parent.mkdir();layout.write_text('{"options":{}}')
            with patch('adws_install_workflow.approved_plan',return_value=plan):
                with self.assertRaisesRegex(RuntimeError,'appeared after review'):launcher.apply_install_plan()
            self.assertEqual(layout.read_text(),'{"options":{}}')

if __name__=='__main__':unittest.main()

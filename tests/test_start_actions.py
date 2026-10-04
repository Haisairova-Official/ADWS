"""Start actions render independently; terminal tests never launch real programs."""
from pathlib import Path
import os
import shlex
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_layout as layout
import adws_launcher as launcher


class StartActionsTests(unittest.TestCase):
    def test_text_image_and_multiple_instances_share_actions_and_one_line_tooltip(self):
        for image in (False, True):
            for mode in ('settings','menu','terminal','custom','none'):
                options={'start_icon_mode':'image' if image else 'custom',
                         'start_image':'/tmp/start.png','start_launcher_command':'fuzzel',
                         'start_label':'Custom icon', 'start_right_mode':mode,
                         'start_right_custom':'printf "%s" "custom value"'}
                state={'apiVersion':2,'builtins':[
                    {'id':'start','instance':'start','options':options},
                    {'id':'start','instance':'another-start','options':{'start_right_mode':'none'}}]}
                with patch.object(layout,'validate_start_images'):
                    cfg=layout.render_waybar_config(state,available=[],base={'custom/applauncher':{'tooltip':False,'tooltip-format':'old\nlong description','on-click':'fuzzel'}})
                definition=cfg['cffi/start-button' if image else 'custom/applauncher']
                command=definition['start_right_command' if image else 'on-click-right']
                tooltip=definition['start_tooltip' if image else 'tooltip-format']
                self.assertEqual(tooltip,layout._tr('开始'));self.assertNotIn('\n',tooltip)
                if mode=='settings':
                    args=shlex.split(command)
                    self.assertTrue(args[1].endswith('adws-config.py'))
                    self.assertEqual(args[2:],['--tab','start','--start-instance','start'])
                elif mode=='menu':self.assertEqual(command,'fuzzel')
                elif mode=='terminal':self.assertEqual(shlex.split(command)[-1],'--terminal')
                elif mode=='custom':self.assertEqual(command,options['start_right_custom'])
                else:self.assertEqual(command,'')
                self.assertEqual(cfg['custom/applauncher#another-start']['on-click-right'],'')

    def test_invalid_custom_action_cannot_be_applied(self):
        for value in ('', '   ', 'bad\x00command', None):
            with self.assertRaises(ValueError):
                layout.start_right_command({'start_right_mode':'custom','start_right_custom':value},'start','fuzzel')
        self.assertEqual(layout.start_right_command({'start_right_mode':'none','start_right_custom':'retained draft'},'start','fuzzel'),'')

    def test_terminal_honors_system_default_before_fallbacks(self):
        with patch.object(launcher.shutil,'which',side_effect=lambda name:'/usr/bin/'+name),patch.dict(os.environ,{'TERMINAL':'foot --login'}):
            self.assertEqual(launcher.terminal_argv(),['/usr/bin/xdg-terminal-exec'])
        with patch.object(launcher.shutil,'which',side_effect=lambda name:'/usr/bin/foot' if name=='foot' else None),patch.dict(os.environ,{'TERMINAL':'foot --login'}),patch.object(launcher.subprocess,'Popen') as launch:
            launcher.launch_terminal()
        launch.assert_called_once_with(['/usr/bin/foot','--login'],cwd=Path.home(),start_new_session=True)
        with patch.object(launcher.shutil,'which',return_value=None):
            with self.assertRaises(RuntimeError):launcher.terminal_argv()

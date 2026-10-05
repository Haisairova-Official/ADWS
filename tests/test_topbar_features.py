import json,os,sys,unittest,tempfile,signal
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_topbar as top
import adws_cava as cava
import adws_topbar_controls as controls
import adws_clipboard as clipboard
class FeatureTests(unittest.TestCase):
 def test_groups_keep_expected_actions_and_widgets(self):
  data=json.loads(top.rendered()[0]);self.assertIn('custom/taskbar-toggle',data['modules-right'])
  self.assertIn('custom/clipboard',data['modules-center']);self.assertIn('custom/cava',data['modules-center'])
  self.assertIn('group/audio',data['modules-right']);self.assertIn('group/brightness',data['modules-right']);self.assertIn('group/powermenu',data['modules-right'])
  self.assertEqual(data['group/powermenu']['modules'],['custom/wlogout','custom/reboot','custom/logout','custom/lockscreen'])
  self.assertIn('adws_topbar_controls.py',data['custom/wlogout']['on-click'])
  self.assertIn('adws_cava.py',data['custom/cava']['exec']);self.assertNotIn('shorin',json.dumps(data).lower())
 def test_cava_frames_reject_malformed_input_and_clamp_values(self):
  self.assertEqual(cava.frame('0;1;2;3;4;5;6;7;8;-1;'),'▁▂▃▄▅▆▇██▁')
  self.assertIsNone(cava.frame('bad'));self.assertIsNone(cava.frame('1;2;'))
 def test_session_planning_does_not_execute_actions(self):
  with patch.dict(os.environ,{'NIRI_SOCKET':'/tmp/test.sock'}):self.assertEqual(controls.session_command('logout'),['niri','msg','action','quit','--skip-confirmation'])
  self.assertEqual(controls.session_command('poweroff'),['systemctl','poweroff'])
 def test_clipboard_binary_round_trip_without_shell(self):
  with patch.object(clipboard,'run',side_effect=[b'\x89PNG\x00example',b'']) as run:
   clipboard.copy_entry('4\t[[ binary data ]]')
   self.assertEqual(run.call_args_list[1].args[0],['wl-copy'])
   self.assertEqual(run.call_args_list[1].kwargs['input'],b'\x89PNG\x00example')
 def test_toggle_rechecks_pid_and_never_signals_topbar(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_STATE_HOME':name}),patch('adws_runtime.pids',return_value=[111,222]),patch.object(controls,'identity',side_effect=['A','B','A','C']),patch.object(controls.os,'kill') as kill:
   result=controls.toggle();self.assertEqual(result['class'],'disabled')
   kill.assert_called_once_with(111,signal.SIGUSR1)
 def test_clipboard_list_is_bounded(self):
  with patch.object(clipboard,'run',return_value=('1\ta\n'*700).encode()):self.assertEqual(len(clipboard.entries()),500)
if __name__=='__main__':unittest.main()

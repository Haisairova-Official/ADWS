import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_color_picker as picker
import adws_topbar as top

class ScreenColorTests(unittest.TestCase):
 def test_scaled_coordinate_and_row_padding(self):
  # Two RGB pixels per row, with two padding bytes between rows.
  data=bytes([255,0,0,0,255,0,99,99,0,0,255,255,255,255])
  self.assertEqual(picker.pixel_hex(data,2,2,8,3,.75,.75,1,1),'#FFFFFF')
  self.assertEqual(picker.pixel_hex(data,2,2,8,3,-1,-1,1,1),'#FF0000')
  self.assertEqual(picker.pixel_hex(data,2,2,8,3,99,99,1,1),'#FFFFFF')
 def test_capture_handles_negative_output_positions_without_shell(self):
  with patch.object(picker.shutil,'which',return_value='/usr/bin/grim'),patch.object(picker.subprocess,'run') as run:
   run.return_value.stdout=b'png';self.assertEqual(picker.capture([(-1920,0,1920,1080)]),[b'png'])
   self.assertEqual(run.call_args.args[0],['grim','-g','-1920,0 1920x1080','-t','png','-'])
   self.assertNotIn('shell',run.call_args.kwargs)
 def test_no_capture_backend_fails_without_wallpaper_fallback(self):
  with patch.object(picker.shutil,'which',return_value=None),patch.object(picker.subprocess,'run') as run:
   with self.assertRaises(RuntimeError):picker.capture([(0,0,100,100)])
   run.assert_not_called()
 def test_clipboard_receives_exact_hex(self):
  with patch.object(picker.subprocess,'run') as run:
   picker.copy_color('#01ABFF');self.assertEqual(run.call_args.args[0],['wl-copy']);self.assertEqual(run.call_args.kwargs['input'],b'#01ABFF')
 def test_native_picker_cancel_has_no_success_feedback(self):
  import tempfile,os
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_RUNTIME_DIR':name}),patch.object(picker.shutil,'which',side_effect=lambda cmd:'/usr/bin/'+cmd),patch.object(picker.subprocess,'run',return_value=Mock(returncode=0,stdout='',stderr='')) as run,patch.object(picker.subprocess,'Popen') as sound:
   self.assertEqual(picker.launch_picker(),0);self.assertIn('--autocopy',run.call_args.args[0]);sound.assert_not_called()
 def test_native_picker_absent_uses_own_ui(self):
  with patch.object(picker.shutil,'which',return_value=None),patch.object(picker,'picker',return_value=0) as fallback:
   self.assertEqual(picker.launch_picker(),0);fallback.assert_called_once()
 def test_own_picker_and_idle_policy_wiring(self):
  d=json.loads(top.rendered()[0]);self.assertIn('adws_color_picker.py',d['custom/colorpicker']['on-click'])
  self.assertNotIn('hyprpicker',d['custom/colorpicker']['on-click']);self.assertFalse(d['idle_inhibitor']['start-activated'])
  self.assertIn('power',d['idle_inhibitor']['on-click-right']);self.assertIn('tooltip-format-activated',d['idle_inhibitor'])
  self.assertNotIn('on-click',d['idle_inhibitor']) # Waybar handles one native toggle.
if __name__=='__main__':unittest.main()

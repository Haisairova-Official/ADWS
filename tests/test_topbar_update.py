import json
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_topbar_update as update
import adws_topbar as top
import adws_waybar as backend

class UpdateTests(unittest.TestCase):
 def test_auto_prefers_yay_and_falls_back_to_paru(self):
  with patch('shutil.which',side_effect=lambda n:'/usr/bin/'+n):self.assertEqual(update.resolve_command(),'yay -Syu')
  with patch('shutil.which',side_effect=lambda n:'/usr/bin/paru' if n=='paru' else None):self.assertEqual(update.resolve_command(),'paru -Syu')
  with patch('shutil.which',return_value=None):
   with self.assertRaises(RuntimeError):update.resolve_command()
 def test_custom_is_explicit_and_required(self):
  self.assertEqual(update.resolve_command('custom','sudo apt update && sudo apt upgrade'),'sudo apt update && sudo apt upgrade')
  with self.assertRaises(ValueError):update.resolve_command('custom',' ')
 def test_terminal_arguments_and_no_execution(self):
  for name,separator in [('kitty','-e'),('alacritty','-e'),('gnome-terminal','--'),('xdg-terminal-exec',None)]:
   argv=update.terminal_command('yay -Syu',[name])
   self.assertEqual(argv[1],separator or '/bin/sh');self.assertIn('yay -Syu\nstatus=$?',argv[-1])
 def test_module_action_round_trip_preserves_other_fields(self):
  module=update.configure_module({'format':'icon','interval':600},'custom','echo "a b"',Path('/tmp/project space'))
  self.assertEqual(update.module_settings(module),('custom','echo "a b"'))
  argv=shlex.split(module['on-click']);self.assertEqual(argv[-1],'echo "a b"');self.assertEqual(module['interval'],600)
  source='// retained\n{"modules-right":["custom/updates"],"custom/updates":{"format":"icon"}}'
  rendered=backend.patch(source,0,{'custom/updates':module});self.assertIn('// retained',rendered)
  self.assertEqual(backend.decode(rendered)['custom/updates'],module)
 def test_default_button_is_system_update_and_right_click_settings(self):
  data=json.loads(top.rendered()[0]);module=data['custom/updates']
  self.assertIn('adws_topbar_update.py',module['on-click']);self.assertIn('--tab waybar',module['on-click-right'])
if __name__=='__main__':unittest.main()

import os,json,tempfile,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_topbar as top
class DefaultTopbarTests(unittest.TestCase):
 def test_fresh_install_has_no_shorin_dependencies_and_quotes_paths(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_CONFIG_HOME':name+'/config','LC_ALL':'C.UTF-8','LANGUAGE':'en'}):
   self.assertTrue(top.install_defaults())
   text=(Path(name)/'config/waybar/config.jsonc').read_text();data=json.loads(text)
   self.assertNotIn('shorin',text.lower());self.assertNotIn('include',data)
   self.assertEqual(data['clock']['format'],'󰥔 {:%H:%M}')
   self.assertIn("'",data['custom/settings']['on-click'])
   self.assertFalse(top.install_defaults())
 def test_original_powerline_and_icon_layout_is_retained(self):
  text,css=top.rendered();data=json.loads(text)
  self.assertIn('custom/right_div#5',data['modules-left'])
  self.assertIn('custom/left_div#1',data['modules-center'])
  self.assertIn('custom/right_div#1',data['modules-center'])
  self.assertEqual(data['custom/right_div#1']['format'],'')
  self.assertIn('custom/applauncher',data['modules-center'])
  self.assertIn('JetBrainsMono Nerd Font Propo',css)
  self.assertIn('background: transparent',css)
 def test_existing_config_and_style_are_never_replaced(self):
  for filename in ('config','config.jsonc'):
   with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_CONFIG_HOME':name}):
    p=Path(name)/'waybar';p.mkdir();(p/filename).write_text('// my Shorin config');(p/'style.css').write_text('my theme')
    self.assertFalse(top.install_defaults());self.assertEqual((p/filename).read_text(),'// my Shorin config');self.assertEqual((p/'style.css').read_text(),'my theme')
 def test_preview_is_nonexclusive_and_has_close_button(self):
  text,_=top.rendered(preview=True);data=json.loads(text)
  self.assertFalse(data['exclusive']);self.assertGreater(data['margin-top'],0)
  self.assertIn('custom/adws-preview-close',data['modules-right'])
  self.assertIn('--stop-preview',data['custom/adws-preview-close']['on-click'])
 def test_autostart_is_idempotent_and_respects_included_waybar(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_CONFIG_HOME':name+'/config'}),patch('adws_autostart.write_config',side_effect=lambda path,text:path.write_text(text)):
   top.install_defaults();root=Path(name);path=root/'config.kdl';path.write_text('// user config\n')
   self.assertTrue(top.add_autostart(path));once=path.read_text();self.assertFalse(top.add_autostart(path));self.assertEqual(path.read_text(),once)
   included=root/'startup.kdl';included.write_text('spawn-at-startup "waybar"\n')
   path.write_text('include "startup.kdl"\n');self.assertFalse(top.add_autostart(path));self.assertEqual(path.read_text(),'include "startup.kdl"\n')
if __name__=='__main__':unittest.main()

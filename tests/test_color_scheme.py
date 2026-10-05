import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_color_scheme as scheme
import adws_wallpaper_colors as colors
import adws_topbar as top

class SchemeTests(unittest.TestCase):
 def test_preferences_reject_unknown_strategy_and_invalid_index(self):
  for value in [{'scheme':'shell-command'},{'mode':'invalid'},{'index':True},{'index':5}]:
   with self.assertRaises(ValueError):colors.validate_preferences(value)
 def test_light_palette_and_safe_command(self):
  roles=['surface','surface_container','surface_container_high','on_surface','on_surface_variant','primary','on_primary','outline_variant','error']
  data={'colors':{'light':{key:'#F0F0F0' for key in roles},'dark':{key:'#101010' for key in roles}}}
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_CONFIG_HOME':name}),patch.object(colors.shutil,'which',return_value='/usr/bin/matugen'):
   image=Path(name)/'some wallpaper.png';image.write_bytes(b'fixture')
   with patch.object(colors.subprocess,'run',side_effect=[Mock(stdout='--source-color-index --prefer'),Mock(returncode=0,stdout=json.dumps(data))]) as run:
    result=colors.extract(image,{'scheme':'scheme-vibrant','mode':'light','index':2})
    self.assertEqual(result['surface'],'#F0F0F0');args=run.call_args.args[0]
    self.assertIn('--dry-run',args);self.assertIn('--source-color-index',args);self.assertIn('scheme-vibrant',args);self.assertIn(str(image),args)
    self.assertEqual((Path(name)/'waybar/colors.css').read_text().count('#F0F0F0'),len(roles))
 def test_current_wallpaper_imports_data_without_running_scripts(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_CONFIG_HOME':name}):
   image=Path(name)/'wallpaper.png';image.write_bytes(b'fixture');folder=Path(name)/'waypaper';folder.mkdir()
   (folder/'config.ini').write_text('[Settings]\nwallpaper = '+str(image)+'\n')
   self.assertEqual(scheme.current_image(),str(image))
 def test_three_mouse_actions_are_distinct(self):
  d=json.loads(top.rendered()[0])['custom/colorpicker']
  self.assertIn('adws_color_picker.py',d['on-click']);self.assertIn('wallpaper',d['on-click-right']);self.assertIn('adws_color_scheme.py',d['on-click-middle'])
 def test_menu_actions_toggle_mode_and_source_strategy(self):
  selected={'scheme':'scheme-content','mode':'dark','index':0}
  self.assertEqual(scheme.changed_preferences(selected,'mode')['mode'],'light')
  cycling=scheme.changed_preferences(selected,'index');self.assertEqual(cycling['index_mode'],'cycle')
  self.assertEqual(scheme.changed_preferences(cycling,'index')['index_mode'],'first')
  self.assertEqual(scheme.changed_preferences(selected,'scheme-neutral')['scheme'],'scheme-neutral')
 def test_menu_uses_adws_frontend(self):
  with patch.object(scheme,'picker',return_value=0) as picker:
   self.assertEqual(scheme.menu(),0);picker.assert_called_once()
 def test_preferences_round_trip(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_CONFIG_HOME':name}):
   value={'scheme':'scheme-content','mode':'light','index':4};colors.save_preferences(value);self.assertEqual(colors.preferences(),value)
if __name__=='__main__':unittest.main()

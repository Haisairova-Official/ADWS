import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_waybar as backend
class ColorsTests(unittest.TestCase):
 def test_preserve_original_theme_and_one_replaceable_override(self):
  original='/* user theme */\n@import "colors.css";\n#clock { color: @secondary; }\n'
  data={'modules-center':['clock','custom/left_div#1']}
  content=backend.color_style(original,{'follow':False,'hover':'rgba(12,34,56,0.5)'},data)
  self.assertTrue(content.startswith(original));self.assertIn('#clock:hover',content);self.assertNotIn('#custom-left_div:hover',content)
  second=backend.color_style(content,{'follow':False,'primary':'#ffffff'},data)
  self.assertEqual(second.count(backend.STYLE_BEGIN),1)
  reverted=backend.color_style(second,{'follow':True},data);self.assertEqual(reverted,original)
 def test_font_override_preserves_icons_colors_and_restores_saved_choice(self):
  original='#custom-actions { font-family: "Nerd Font"; }\n@define-color primary #aabbcc;\n'
  first=backend.font_style(original,{'follow':False,'family':'Noto Sans CJK SC','size':12})
  second=backend.font_style(first,{'follow':True,'family':'Sans','size':10})
  self.assertEqual(second.count(backend.FONT_BEGIN),1);self.assertTrue(second.startswith(original))
  self.assertNotIn('#custom-actions',second.split(backend.FONT_BEGIN)[1])
  with tempfile.TemporaryDirectory() as name,patch.object(backend,'processes',return_value=[]):
   root=Path(name);config=root/'config.jsonc';config.write_text('{}');(root/'style.css').write_text(second)
   self.assertEqual(backend.load_style(config)['font_settings'],{'follow':True,'family':'Sans','size':10})
  for settings in [{'family':'bad\nname','size':10},{'family':'Sans','size':0},{'family':'Sans','size':100}]:
   with self.assertRaises(ValueError):backend.font_style(original,settings)
 def test_arrow_geometry_tracks_configured_height_without_changing_text_font(self):
  data={'name':'adws-top','height':30,'modules-center':['custom/left_div#1','clock','custom/right_div#1']}
  small=backend.geometry_style('/* preserve */',data)
  self.assertIn('min-width: 15.0px',small);self.assertIn('background-size: 100% 100%',small)
  data['height']=60;large=backend.geometry_style(small,data)
  self.assertEqual(large.count(backend.GEOMETRY_BEGIN),1);self.assertIn('min-width: 30.0px',large)
  self.assertNotIn('#clock',large);self.assertTrue(large.startswith('/* preserve */'))
 def test_reject_css_injection(self):
  with self.assertRaises(ValueError):backend.color_style('',{'follow':False,'background':'red; } * { color: black'}, {})
 def test_bundle_conflict_and_symlink_protection(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_STATE_HOME':name+'/state'}),patch.object(backend,'reload',return_value=0):
   folder=Path(name);config=folder/'config.jsonc';config.write_text('{}')
   target=folder/'theme.css';target.write_text('/* mine */\n');style=folder/'style.css';style.symlink_to(target)
   backend.save_with_style(config,'{}','{"height":20}',style,'/* mine */\n','/* new */\n')
   self.assertTrue(style.is_symlink());self.assertEqual(target.read_text(),'/* new */\n')
   with self.assertRaises(ValueError):backend.save_with_style(config,'{"height":20}','{}',style,'/* mine */\n','/* unwanted */')
   self.assertEqual(config.read_text(),'{"height":20}')
if __name__=='__main__':unittest.main()

import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_waybar as backend
import adws_waybar_presets as presets

class PresetTests(unittest.TestCase):
 def test_layouts_have_distinct_roles_and_no_dotfile_scripts(self):
  models={}
  for key,_,_ in presets.PRESETS:
   text,css=presets.rendered(key);models[key]=json.loads(text)
   self.assertEqual(models[key]['adws-preset'],key)
   self.assertNotIn('ml4w',text.lower());self.assertNotIn('.config/scripts',text)
   self.assertIn('@import "colors.css";',css)
  self.assertIn('custom/left_div#1',models['standard']['modules-center'])
  self.assertFalse(any('div#' in module for slot in ('left','center','right') for module in models['simple']['modules-'+slot]))
  self.assertEqual(models['status']['modules-left'],['cpu','memory'])
  self.assertNotIn('custom/applauncher',models['status']['modules-right'])
  self.assertIn('toggle-overview',models['gnome']['group/gnome-overview']['on-click'])
  self.assertEqual(models['gnome']['modules-right'],['group/gnome-system'])
  self.assertEqual(models['gnome']['modules-left'],['group/gnome-overview'])
  self.assertNotIn('tray',models['gnome']['group/gnome-system']['modules'])
  self.assertIn('calendar',models['gnome']['clock']['on-click'])
  self.assertEqual(models['gnome']['modules-center'],['clock'])
 def test_preview_never_reserves_space_and_close_occurs_once(self):
  for key,_,_ in presets.PRESETS:
   data=json.loads(presets.rendered(key,preview=True)[0]);self.assertFalse(data['exclusive'])
   self.assertEqual(data['modules-right'].count('custom/adws-preview-close'),1)
 def test_replace_only_selected_bar_preserves_outer_comments(self):
  text='// user\n[{"name":"one"}, /* keep */ {"name":"two"}]'
  result=backend.replace_bar(text,1,{'name':'new'})
  self.assertIn('// user',result);self.assertIn('/* keep */',result)
  self.assertEqual(backend.decode(result),[{'name':'one'},{'name':'new'}])
 def test_backup_copies_includes_imports_and_preserves_symlinks(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);real=root/'actual.jsonc';real.write_text('{"include":["modules.jsonc"]}')
   config=root/'config.jsonc';config.symlink_to(real)
   (root/'modules.jsonc').write_text('{"clock":{"format":"test"}}')
   style=root/'style.css';style.write_text('@import "colors.css"; /* @import "absent.css"; */')
   (root/'colors.css').write_text('@define-color primary #ffffff;')
   before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
   result=backend.backup_current(config,style,root/'backups');manifest=json.loads((result/'manifest.json').read_text())
   self.assertEqual(len(manifest['files']),4);self.assertTrue(config.is_symlink())
   for source in manifest['files']:
    self.assertEqual((result/source['snapshot']).read_bytes(),Path(source['resolved']).read_bytes())
   for filename,data in before.items():self.assertEqual((root/filename).read_bytes(),data)
 def test_backup_cycle_is_bounded_and_missing_reference_does_not_create_backup(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);config=root/'config.jsonc';style=root/'style.css';style.write_text('')
   config.write_text('{"include":"config.jsonc"}')
   result=backend.backup_current(config,style,root/'backups');self.assertEqual(len(json.loads((result/'manifest.json').read_text())['files']),2)
   config.write_text('{"include":"missing.jsonc"}')
   with self.assertRaises(FileNotFoundError):backend.backup_current(config,style,root/'not-created')
   self.assertFalse((root/'not-created').exists())
if __name__=='__main__':unittest.main()

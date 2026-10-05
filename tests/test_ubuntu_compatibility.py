"""Regressions for the mounted Mint/Ubuntu failure report."""
import json,sys,tempfile,shutil,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_health as health
import adws_waybar as waybar
import adws_topbar as topbar
import adws_runtime as runtime

class UbuntuCompatibilityTests(unittest.TestCase):
 def test_old_or_feature_disabled_waybar_is_rejected(self):
  with tempfile.TemporaryDirectory() as name:
   binary=Path(name)/'waybar'
   for payload,missing in [(b'\x7fELF\0clock\0','cffi/'),(b'\x7fELF\0cffi/\0','niri/workspaces')]:
    binary.write_bytes(payload);errors=health.waybar_capability_errors(binary)
    self.assertTrue(errors);self.assertIn(missing,errors[0])
   binary.write_bytes(b'\x7fELF\0cffi/\0niri/workspaces\0')
   self.assertEqual(health.waybar_capability_errors(binary),[])
 def test_missing_or_wrapper_waybar_reports_error(self):
  with tempfile.TemporaryDirectory() as name:
   binary=Path(name)/'waybar';self.assertTrue(health.waybar_capability_errors(binary))
   binary.write_text('#!/bin/sh\n');self.assertTrue(health.waybar_capability_errors(binary))
 def test_start_does_not_launch_empty_bar(self):
  with patch.object(health,'waybar_capability_errors',return_value=['unsupported']),patch.object(health,'validate_waybar',return_value=[]),patch.object(runtime.subprocess,'Popen') as spawn:
   self.assertEqual(runtime.start_taskbar(Path('/fixture/config'),Path('/fixture/style')),(False,'unsupported'));spawn.assert_not_called()
 def test_unicode_preset_supports_backup_and_import(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name)/'桌面/adws';shutil.copytree(topbar.ROOT/'config',root/'config')
   text,css=topbar.rendered(root)
   self.assertIn(str(root),css);self.assertNotIn(r'\u684c',css)
   config=root/'config.jsonc';config.write_text(text)
   style=root/'style.css';style.write_text(css);(root/'colors.css').write_text('')
   records=waybar.bundle_records(config,style)
   self.assertIn((root/'config/waybar/arrow-left-symbolic.svg').resolve(),records)
   dest=Path(name)/'新配置';dest.mkdir()
   result=waybar.import_bundle(config,dest/'config.jsonc',dest/'style.css',style)
   self.assertNotIn(r'\u',result['style']);self.assertIn('新配置',result['style'])
   legacy=css.replace(str(root),json.dumps(str(root))[1:-1]);style.write_text(legacy)
   self.assertEqual(len(waybar.bundle_records(config,style)),len(records))
 def test_literal_unicode_escape_filename_is_preserved(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);literal=root/r'\u684c.svg';literal.write_text('literal');(root/'桌.svg').write_text('other')
   self.assertEqual(waybar.reference(root/'style.css',literal.name),literal)
if __name__=='__main__':unittest.main()

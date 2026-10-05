"""Preserve JSONC/theme data and target only the selected standalone process."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch as mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_waybar as bar
class WaybarTests(unittest.TestCase):
 def test_restore_legacy_partial_and_config_only_manifest(self):
  with tempfile.TemporaryDirectory() as name,mock.dict(os.environ,{'XDG_STATE_HOME':name+'/state'}),mock.object(bar,'reload',return_value=1):
   root=Path(name);config=root/'config.jsonc';style=root/'style.css';config.write_text('{"height":30}')
   saved=bar.save(config,config.read_text(),'{"height":40}')
   bar.restore_backup(saved['backup'],config,style);self.assertEqual(bar.decode(config.read_text())['height'],30)
   style.write_text('#clock {color:white;}');old=bar.backup_folder()/'appearance-old';old.mkdir();(old/'config.jsonc').write_text('{"height":20}');(old/'style.css').write_text('#clock {color:red;}')
   self.assertIn(old,bar.list_backups(config));bar.restore_backup(old,config,style)
   self.assertEqual(bar.decode(config.read_text())['height'],20);self.assertIn('red',style.read_text())
 def test_complete_import_restore_and_restart_rollback(self):
  with tempfile.TemporaryDirectory() as name,mock.dict(os.environ,{'XDG_STATE_HOME':name+'/state'}),mock.object(bar,'reload',return_value=1):
   root=Path(name);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
   (source/'nested.jsonc').write_text('{"clock":{"format":"{:%H:%M}"}}')
   (source/'modules.jsonc').write_text('{"include":"nested.jsonc"}')
   (source/'config.jsonc').write_text('// imported\n{"include":["modules.jsonc"],"height":30}')
   (source/'style.css').write_text('@import "colors.css"; #clock {background-image:url("icon.svg");}')
   (source/'colors.css').write_text('@define-color accent #ffffff;')
   (source/'icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
   config=target/'config.jsonc';style=target/'style.css';config.write_text('{"height":25}');style.write_text('#clock {color:white;}')
   before=config.read_text();before_style=style.read_text();bundle=bar.import_bundle(source/'config.jsonc',config,style)
   self.assertEqual(bundle['count'],6);self.assertEqual(config.read_text(),before)
   result=bar.save_bundle(config,before,bundle['text'],style,before_style,bundle['style'],bundle['files'])
   import shutil;shutil.rmtree(source)
   records=bar.bundle_records(config,style);self.assertEqual(len(records),6)
   self.assertTrue(any(kind=='asset' for _,_,kind in records.values()))
   restored=bar.restore_backup(result['backup'],config,style)
   self.assertEqual(config.read_text(),before);self.assertEqual(style.read_text(),before_style)
   bar.restore_backup(restored['backup'],config,style);self.assertEqual(len(bar.bundle_records(config,style)),6)
   backup=Path(restored['backup']);manifest=json.loads((backup/'manifest.json').read_text());(backup/manifest['files'][0]['snapshot']).write_text('tampered')
   with self.assertRaises(ValueError):bar.restore_backup(backup,config,style)
   live=config.read_text()
   with mock.object(bar,'reload',side_effect=[RuntimeError('crash'),1]):
    with self.assertRaises(RuntimeError):bar.save(config,live,'{"height":99}')
   self.assertEqual(config.read_text(),live)
 def test_import_stages_comments_includes_and_rejects_invalid_data(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);source=root/'source.jsonc';include=root/'modules.jsonc';include.write_text('{"clock":{}}')
   source.write_text('// keep\n[{"include":["modules.jsonc"],"height":35},{"height":40}]')
   original=source.read_text();result=bar.import_config(source)
   self.assertEqual(source.read_text(),original);self.assertIn('// keep',result['text'])
   self.assertEqual(result['data'][0]['include'],[str(include)])
   self.assertEqual(result['data'][1]['height'],40)
   source.write_text('{"include":42}')
   with self.assertRaises(ValueError):bar.import_config(source)
   source.write_text('[]')
   with self.assertRaises(ValueError):bar.import_config(source)
   with self.assertRaises(ValueError):bar.import_config(root/'config-bottom.jsonc')
 def test_comments_includes_and_other_modules_survive(self):
  text='''{ // Keep my layout\n "include": ["modules.jsonc",],\n "height": 30, // my height\n "modules-left": ["clock"],\n "custom/test": {"exec":"https://example/x/*hi*/", "nested":{"height":90}}\n}'''
  result=bar.patch(text,0,{'height':38,'spacing':5,'modules-left':['clock','tray']})
  self.assertIn('// Keep my layout',result);self.assertIn('// my height',result)
  self.assertIn('"include": ["modules.jsonc",]',result)
  data=bar.decode(result);self.assertEqual(data['height'],38);self.assertEqual(data['custom/test']['nested']['height'],90)
  self.assertEqual(data['modules-left'],['clock','tray']);self.assertEqual(data['spacing'],5)
 def test_multibar_updates_only_selected_root(self):
  text='[{"name":"one","height":30,"nested":{"height":90}}, /* KEEP */ {"name":"two","height":40}]'
  result=bar.patch(text,1,{'height':50});self.assertIn('/* KEEP */',result)
  self.assertEqual(bar.decode(result)[0],bar.decode(text)[0]);self.assertEqual(bar.decode(result)[1]['height'],50)
 def test_empty_and_trailing_comma_objects(self):
  for text in ['{}','{ /* keep */ }','{"height":30, // comment\n}']:
   result=bar.patch(text,0,{'spacing':2});self.assertEqual(bar.decode(result)['spacing'],2)
 def test_symlinks_backups_and_conflicts(self):
  with tempfile.TemporaryDirectory() as name,mock.dict(os.environ,{'XDG_STATE_HOME':name+'/state'}),mock.object(bar,'reload',return_value=0):
   root=Path(name);real=root/'real.jsonc';real.write_text('{"height":30}');link=root/'config.jsonc';link.symlink_to(real)
   result=bar.save(link,real.read_text(),'{"height":40}');self.assertTrue(link.is_symlink());self.assertEqual(next(Path(result['backup']).glob('00-*')).read_text(),'{"height":30}')
   with self.assertRaises(ValueError):bar.save(link,'stale','{}')
   self.assertEqual(real.read_text(),'{"height":40}')
   with self.assertRaises(ValueError):bar.save(root/'config-bottom.jsonc','{}','{}')
   alias=root/'alias.jsonc';alias.symlink_to(root/'config-bottom.jsonc')
   self.assertTrue(bar.is_adws(alias))
 def test_reload_uses_safe_restart_even_for_custom_signals_or_missing_instances(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);config=root/'config.jsonc';style=root/'style.css';config.write_text('{"on-sigusr2":"toggle"}');style.write_text('')
   processes=[{'pid':10,'start':'123','config':config,'style':style}]
   for running in (processes,[]):
    with mock.object(bar,'processes',return_value=running),mock.object(bar,'restart') as restart,mock.object(bar.os,'kill') as kill:
     self.assertEqual(bar.reload(config),1);restart.assert_called_once_with(config,style);kill.assert_not_called()
 def test_autostart_handles_includes_and_preserves_other_apps(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);config=root/'config.jsonc';style=root/'style.css';config.write_text('{}');style.write_text('')
   niri=root/'niri.kdl';include=root/'start.kdl'
   niri.write_text('include "start.kdl"\nspawn-at-startup "foot"\n')
   include.write_text('spawn-at-startup "waybar" "-c" "'+str(config)+'"\nspawn-at-startup "fcitx5"\n')
   with mock.object(bar,'default_config',return_value=config):
    self.assertTrue(bar.autostart_status(config,niri)['enabled'])
    with mock('adws_autostart.write_config',side_effect=lambda p,s:p.write_text(s)):
     bar.set_autostart(config,style,False,niri)
     self.assertEqual(include.read_text(),'spawn-at-startup "fcitx5"\n');self.assertIn('foot',niri.read_text())
     self.assertFalse(bar.autostart_status(config,niri)['enabled'])
     bar.set_autostart(config,style,True,niri);first=niri.read_text();bar.set_autostart(config,style,True,niri)
     self.assertEqual(niri.read_text(),first);self.assertTrue(bar.autostart_status(config,niri)['enabled'])
 def test_restart_starts_missing_bar_and_only_stops_exact_profile(self):
  with tempfile.TemporaryDirectory() as name,mock.dict(os.environ,{'XDG_STATE_HOME':name}):
   root=Path(name);config=root/'config.jsonc';style=root/'style.css';config.write_text('{}');style.write_text('')
   previous={'pid':10,'start':'123','config':config}
   other={'pid':11,'start':'124','config':root/'other.jsonc'}
   import subprocess,time,shutil
   for snapshots,expected_kills in [([[],[]],0),([[previous,other],[previous,other],[other]],1)]:
    with mock.object(bar,'processes',side_effect=snapshots),mock.object(bar.os,'kill') as kill,mock.object(shutil,'which',return_value='/usr/bin/waybar'),mock.object(subprocess,'Popen') as spawn,mock.object(time,'sleep'):
     spawn.return_value.poll.return_value=None;spawn.return_value.pid=99
     self.assertEqual(bar.restart(config,style)['pid'],99)
     self.assertEqual(kill.call_count,expected_kills)
     if expected_kills:kill.assert_called_once_with(10,bar.signal.SIGTERM)
     self.assertEqual(spawn.call_args.args[0],['/usr/bin/waybar','-c',str(config),'-s',str(style)])
 def test_restart_refuses_adws_and_invalid_config_before_stopping(self):
  with tempfile.TemporaryDirectory() as name,mock.object(bar.os,'kill') as kill:
   root=Path(name);style=root/'style.css';style.write_text('')
   with self.assertRaises(ValueError):bar.restart(root/'config-bottom.jsonc',style)
   config=root/'config.jsonc';config.write_text('invalid')
   with self.assertRaises(ValueError):bar.restart(config,style)
   kill.assert_not_called()
 def test_duplicate_root_values_refused(self):
  with self.assertRaises(ValueError):bar.patch('{"height":30,"height":40}',0,{'height':50})
if __name__=='__main__':unittest.main()

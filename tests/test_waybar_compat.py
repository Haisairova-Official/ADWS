"""Dependency repair decisions, binary selection and failed build recovery."""
import os,sys,tempfile,subprocess,io,hashlib,fcntl
from pathlib import Path
from unittest.mock import patch,Mock
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_waybar_compat as compat

class WaybarCompatibilityTests(unittest.TestCase):
 def test_compatible_system_needs_no_prompts(self):
  confirm,install=Mock(),Mock()
  with patch.object(compat,'resolve_waybar',return_value='/usr/bin/waybar'):
   self.assertEqual(compat.ensure_waybar(confirm,install),'/usr/bin/waybar')
  confirm.assert_not_called();install.assert_not_called()
 def test_package_install_success_skips_build(self):
  confirm,install=Mock(return_value=True),Mock()
  with patch.object(compat,'resolve_waybar',side_effect=[None,'/usr/bin/waybar']),patch.object(compat,'build_waybar') as build:
   self.assertEqual(compat.ensure_waybar(confirm,install,lambda _:None),'/usr/bin/waybar')
   install.assert_called_once_with(['waybar']);build.assert_not_called()
 def test_old_package_offers_private_build(self):
  confirm,install=Mock(return_value=True),Mock()
  with patch.object(compat,'resolve_waybar',return_value=None),patch.object(compat,'build_waybar',return_value='/private/bin/waybar') as build:
   self.assertEqual(compat.ensure_waybar(confirm,install,lambda _:None),'/private/bin/waybar')
   self.assertEqual(confirm.call_count,2);self.assertEqual(install.call_args_list[0].args,(['waybar'],))
   self.assertEqual(install.call_args_list[1].kwargs,{'groups':['waybar-build']});build.assert_called_once()
 def test_decline_preserves_files_and_does_not_build(self):
  with patch.object(compat,'resolve_waybar',return_value=None),patch.object(compat,'build_waybar') as build:
   install=Mock()
   with self.assertRaises(RuntimeError):compat.ensure_waybar(lambda _:False,install,lambda _:None)
   install.assert_not_called();build.assert_not_called()
 def test_package_error_can_fall_back_to_build(self):
  install=Mock(side_effect=[subprocess.CalledProcessError(1,['apt-get']),None])
  with patch.object(compat,'resolve_waybar',return_value=None),patch.object(compat,'build_waybar',return_value='/private/bin/waybar'):
   self.assertEqual(compat.ensure_waybar(lambda _:True,install,lambda _:None),'/private/bin/waybar')
 def test_private_binary_survives_old_system_and_priority_is_explicit(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);system=root/'system';system.write_bytes(b'\x7fELF\0clock\0')
   managed=root/'private';(managed/'bin').mkdir(parents=True);binary=managed/'bin/waybar'
   binary.write_bytes(b'\x7fELF\0cffi/\0niri/workspaces\0');binary.chmod(0o755)
   with patch.object(compat,'managed_prefix',return_value=managed),patch.object(compat.shutil,'which',return_value=str(system)):
    self.assertEqual(compat.resolve_waybar(),str(binary))
    system.write_bytes(binary.read_bytes());self.assertEqual(compat.resolve_waybar(),str(system))
    system.unlink();self.assertEqual(compat.resolve_waybar(),str(binary))
 def test_invalid_staged_binary_never_replaces_previous_build(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);old=root/'waybar';old.mkdir();(old/'keep').write_text('old')
   stage=root/'stage';stage.mkdir()
   with patch.object(compat,'validate_build',side_effect=RuntimeError('bad')):
    with self.assertRaises(RuntimeError):compat.activate(stage,old)
   self.assertEqual((old/'keep').read_text(),'old');self.assertTrue(stage.exists())
 def test_failed_activation_restores_previous_and_success_keeps_backup(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);old=root/'waybar';old.mkdir();(old/'keep').write_text('old')
   stage=root/'stage';stage.mkdir();(stage/'keep').write_text('new')
   with patch.object(compat,'validate_build',side_effect=[None,RuntimeError('bad')]):
    with self.assertRaises(RuntimeError):compat.activate(stage,old)
   self.assertEqual((old/'keep').read_text(),'old')
   stage.mkdir();(stage/'keep').write_text('new')
   with patch.object(compat,'validate_build'):
    compat.activate(stage,old)
   self.assertEqual((old/'keep').read_text(),'new');self.assertEqual(next(root.glob('waybar-backup-*')).joinpath('keep').read_text(),'old')
 def test_unexpected_upstream_commit_is_rejected(self):
  with tempfile.TemporaryDirectory() as name,patch.object(compat,'run'),patch.object(compat.subprocess,'check_output',return_value='wrong'):
   with self.assertRaises(RuntimeError):compat.clone_source(Path(name),Mock(),False)
 def test_fallback_dependency_rejects_bad_hash_then_uses_direct(self):
  from adws_update import github_urls
  payload=b'checksum-pinned upstream dependency'
  with tempfile.TemporaryDirectory() as name:
   source=Path(name);(source/'subprojects').mkdir()
   (source/'subprojects/gtk-layer-shell.wrap').write_text(
    '[wrap-file]\nsource_url=https://github.com/upstream/archive.tar.gz\n'
    'source_filename=layer-shell.tar.gz\nsource_hash='+hashlib.sha256(payload).hexdigest()+'\n')
   responses=[io.BytesIO(b'corrupt'),io.BytesIO(payload)]
   with patch('adws_update.github_urls',return_value=['https://proxy.invalid/archive','https://github.com/upstream/archive.tar.gz']),patch.object(compat.urllib.request,'urlopen',side_effect=responses) as download:
    compat.cache_layer_shell(source,True)
   self.assertEqual(download.call_count,2)
   self.assertEqual((source/'subprojects/packagecache/layer-shell.tar.gz').read_bytes(),payload)
 def test_bad_dependency_is_removed(self):
  with tempfile.TemporaryDirectory() as name:
   source=Path(name);(source/'subprojects').mkdir()
   (source/'subprojects/gtk-layer-shell.wrap').write_text(
    '[wrap-file]\nsource_url=https://github.com/upstream/archive.tar.gz\n'
    'source_filename=layer-shell.tar.gz\nsource_hash=wrong\n')
   with patch('adws_update.github_urls',return_value=['https://github.com/upstream/archive.tar.gz']),patch.object(compat.urllib.request,'urlopen',return_value=io.BytesIO(b'corrupt')):
    with self.assertRaises(RuntimeError):compat.cache_layer_shell(source,False)
   self.assertFalse((source/'subprojects/packagecache/layer-shell.tar.gz').exists())
 def test_concurrent_build_is_rejected_before_downloading(self):
  with tempfile.TemporaryDirectory() as name:
   prefix=Path(name)/'waybar'
   with (prefix.parent/'waybar-build.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with patch.object(compat,'managed_prefix',return_value=prefix),patch.object(compat,'_build_waybar') as build:
     with self.assertRaises(RuntimeError):compat.build_waybar()
     build.assert_not_called()
if __name__=='__main__':unittest.main()

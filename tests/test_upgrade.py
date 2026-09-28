import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_upgrade as upgrade
import adws_runtime


def archive(path, version='1.28-A'):
    with zipfile.ZipFile(path, 'w') as z:
        files={'build-info.json':json.dumps({'display_version':version}), 'adws':'#!/bin/sh\nexit 0\n',
               'tools/adws_runtime.py':'', 'tools/adws_uninstall.py':'', 'tools/adws-config.py':'',
               'src/niri-desktop-layer/desktop-layer':'', 'src/niri-desktop-layer/start-desktop-layer':'',
               'config/custom.json':'new default'}
        files.update({'binaries/'+name:'new '+name for name in upgrade.LIBRARIES})
        for name, data in files.items():z.writestr('ADWS/'+name,data)


class ArchiveTests(unittest.TestCase):
    def test_download_proxy_then_direct_and_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            z=Path(folder)/'fixture.zip';archive(z);payload=z.read_bytes()
            checksum=hashlib.sha256(payload).hexdigest()
            with patch.dict(os.environ,{'ADWS_GITHUB_PROXY':'https://ghproxy.example/'}), patch.object(upgrade.urllib.request,'urlopen',side_effect=[io.BytesIO(b'bad proxy'),io.BytesIO(payload)]) as request:
                upgrade.download('https://github.com/a/b.zip',Path(folder)/'download.zip',True,checksum)
                self.assertEqual([c.args[0].full_url for c in request.call_args_list],['https://ghproxy.example/https://github.com/a/b.zip','https://github.com/a/b.zip'])
            with patch.object(upgrade.urllib.request,'urlopen',return_value=io.BytesIO(payload)) as request:
                upgrade.download('https://github.com/a/b.zip',Path(folder)/'direct.zip',False)
                self.assertEqual(request.call_args.args[0].full_url,'https://github.com/a/b.zip')

    def test_unsafe_archives_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for index,name in enumerate(('../escape','/absolute','ADWS/../../escape','ADWS/link')):
                z=root/f'{index}.zip'
                with zipfile.ZipFile(z,'w') as output:
                    info=zipfile.ZipInfo(name)
                    if name.endswith('link'):info.external_attr=(stat.S_IFLNK|0o777)<<16
                    output.writestr(info,'target')
                with self.assertRaises(ValueError):upgrade.extract(z,root/f'out{index}')
            self.assertFalse((root.parent/'escape').exists())

    def test_arch_asset_selection_uses_canonical_repository(self):
        release={'tag_name':'v1.28-A','assets':[{'name':'ADWS1.28-A_for_arch.zip','browser_download_url':'https://evil.invalid','digest':'sha256:'+'a'*64}]}
        with patch.object(upgrade.platform,'freedesktop_os_release',return_value={'ID':'arch'}), patch.object(upgrade.platform,'machine',return_value='x86_64'):
            url,digest,prebuilt=upgrade.package(release)
            self.assertTrue(url.startswith('https://github.com/Haisairova-Official/ADWS/releases/download/v1.28-A/'))
            self.assertEqual(digest,'a'*64);self.assertTrue(prebuilt)
        with patch.object(upgrade.platform,'freedesktop_os_release',return_value={'ID':'ubuntu'}):
            url,digest,prebuilt=upgrade.package(release)
            self.assertTrue(url.endswith('/archive/refs/tags/v1.28-A.zip'));self.assertFalse(prebuilt)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.root=self.home/'installed'
        self.root.mkdir();(self.root/'build-info.json').write_text('{"display_version":"1.27-D"}')
        (self.root/'adws').write_text('old command')
        for name in upgrade.PRESERVE:
            path=self.root/name;path.mkdir(parents=True,exist_ok=True);(path/'custom.json').write_text('user data')
        self.state=self.home/'state/adws';self.state.mkdir(parents=True)
        self.record=self.state/'install-record.json'
        self.record.write_text(json.dumps({'root':str(self.root),'configs':['preserve-me'],'libraries':{}}))
        self.libdir=self.home/'.local/lib/waybar';self.libdir.mkdir(parents=True)
        for name in upgrade.LIBRARIES:(self.libdir/name).write_text('old '+name)
        self.source=self.home/'source.zip';archive(self.source)
        self.result={'available':True,'release':{'tag_name':'v1.28-A','prerelease':True},'use_proxy':True}
        self.active={'desktop'}
        self.patches=[patch.dict(os.environ,{'HOME':str(self.home),'XDG_STATE_HOME':str(self.home/'state')}),
                      patch.object(upgrade,'ROOT',self.root),
                      patch.object(upgrade,'package',return_value=('https://github.com/fixture.zip',None,False)),
                      patch.object(upgrade,'download',side_effect=lambda url,target,*args:shutil.copy2(self.source,target)),
                      patch.object(upgrade,'prepare_libraries',return_value={n:Path('binaries')/n for n in upgrade.LIBRARIES}),
                      patch.object(adws_runtime,'pids',side_effect=lambda component:[123] if component in self.active else []),
                      patch.object(upgrade,'control',side_effect=self.change_process_state)]
        self.mocks=[p.start() for p in self.patches]
        for p in self.patches:self.addCleanup(p.stop)
        self.control=self.mocks[-1]

    def change_process_state(self, root, component, operation, log):
        if operation=='--stop':self.active.discard(component)
        elif operation=='--start':self.active.add(component)

    def verify_old(self):
        self.assertEqual((self.root/'adws').read_text(),'old command')
        for name in upgrade.LIBRARIES:self.assertEqual((self.libdir/name).read_text(),'old '+name)
        self.assertEqual(json.loads(self.record.read_text())['libraries'],{})
        for name in upgrade.PRESERVE:self.assertEqual((self.root/name/'custom.json').read_text(),'user data')

    def test_success_preserves_configuration_and_restarts_only_running_components(self):
        messages=[];result=upgrade.install_update(self.result,messages.append)
        self.assertIn('backup',result.lower())
        self.assertEqual(json.loads((self.root/'build-info.json').read_text())['display_version'],'1.28-A')
        for name in upgrade.PRESERVE:self.assertEqual((self.root/name/'custom.json').read_text(),'user data')
        for name in upgrade.LIBRARIES:self.assertEqual((self.libdir/name).read_text(),'new '+name)
        data=json.loads(self.record.read_text());self.assertEqual(data['configs'],['preserve-me'])
        backup=Path(data['last_update_backup']);self.assertEqual((backup/'source/adws').read_text(),'old command')
        self.assertEqual([(c.args[1],c.args[2]) for c in self.control.call_args_list],[('desktop','--stop'),('desktop','--start')])
        self.assertEqual(len(messages),3)

    def test_build_failure_does_not_stop_or_modify_install(self):
        self.mocks[4].side_effect=RuntimeError('compiler failed')
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.control.assert_not_called();self.verify_old()

    def test_version_mismatch_and_downgrade_never_install(self):
        archive(self.source,'9.0 Release')
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.control.assert_not_called();self.verify_old()
        self.result['release']['tag_name']='v1.25'
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.verify_old()

    def test_partial_library_copy_is_rolled_back(self):
        original=upgrade.atomic_copy;failed=False
        def copy(source,target):
            nonlocal failed
            if target.name=='libadws_panel.so' and not failed:
                failed=True;raise OSError('disk full')
            original(source,target)
        with patch.object(upgrade,'atomic_copy',side_effect=copy), self.assertRaises(RuntimeError):
            upgrade.install_update(self.result,lambda _:None)
        self.verify_old()

    def test_restart_failure_restores_old_version(self):
        def control(root,component,operation,log):
            if operation=='--start' and json.loads((root/'build-info.json').read_text())['display_version']=='1.28-A':
                raise RuntimeError('new component failed')
            self.change_process_state(root,component,operation,log)
        self.control.side_effect=control
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.verify_old()
        self.assertEqual(self.control.call_args.args[2],'--start')

    def test_stop_failure_does_not_rewrite_files_or_start_duplicate(self):
        before={path:path.stat().st_ino for path in [self.record,*self.libdir.iterdir()]}
        self.control.side_effect=RuntimeError('stop failed')
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.verify_old()
        self.assertEqual([(c.args[1],c.args[2]) for c in self.control.call_args_list],[('desktop','--stop')])
        self.assertEqual({path:path.stat().st_ino for path in before},before)

    def test_stop_success_with_live_process_aborts_replacement(self):
        self.control.side_effect=lambda *args:None
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.verify_old()
        self.assertFalse(any(c.args[2]=='--start' for c in self.control.call_args_list))

    def test_partial_stop_restarts_only_component_that_stopped(self):
        self.active.add('taskbar')
        def control(root,component,operation,log):
            if component=='taskbar' and operation=='--stop':raise RuntimeError('taskbar did not stop')
            self.change_process_state(root,component,operation,log)
        self.control.side_effect=control
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.verify_old()
        self.assertEqual([(c.args[1],c.args[2]) for c in self.control.call_args_list],
                         [('desktop','--stop'),('taskbar','--stop'),('desktop','--start')])

    def test_rollback_waits_for_new_process_to_stop(self):
        def control(root,component,operation,log):
            version=json.loads((root/'build-info.json').read_text())['display_version']
            if version=='1.28-A':
                if operation=='--start':self.active.add(component)
                raise RuntimeError('new component unresponsive')
            self.change_process_state(root,component,operation,log)
        self.control.side_effect=control
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.assertEqual(json.loads((self.root/'build-info.json').read_text())['display_version'],'1.28-A')
        for name in upgrade.LIBRARIES:self.assertEqual((self.libdir/name).read_text(),'new '+name)
        backup=next(self.home.glob('.installed-backup-*'))
        self.assertEqual((backup/'source/adws').read_text(),'old command')
        self.assertEqual(self.control.call_args.args[2],'--stop')

    def test_failed_library_restore_never_starts_mixed_version(self):
        original=upgrade.atomic_copy
        def copy(source,target):
            if target.name=='libadws_panel.so':raise OSError('persistent disk error')
            original(source,target)
        with patch.object(upgrade,'atomic_copy',side_effect=copy),self.assertRaises(RuntimeError):
            upgrade.install_update(self.result,lambda _:None)
        self.assertFalse(any(c.args[2]=='--start' for c in self.control.call_args_list))
        backup=next(self.home.glob('.installed-backup-*'))
        self.assertEqual((backup/'libraries/libadws_panel.so').read_text(),'old libadws_panel.so')

    def test_update_and_rollback_keep_inventory_link_and_permissions(self):
        target=self.home/'personal-inventory.json';self.record.rename(target);self.record.symlink_to(target)
        target.chmod(0o600)
        def fail_start(root,component,operation,log):
            if operation=='--start' and json.loads((root/'build-info.json').read_text())['display_version']=='1.28-A':
                raise RuntimeError('start failed')
            self.change_process_state(root,component,operation,log)
        self.control.side_effect=fail_start
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.assertTrue(self.record.is_symlink())
        self.assertEqual(self.record.resolve(),target)
        self.assertEqual(target.stat().st_mode & 0o777,0o600)
        self.verify_old()
        self.control.side_effect=self.change_process_state
        upgrade.install_update(self.result,lambda _:None)
        self.assertTrue(self.record.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads(target.read_text())['root'],str(self.root))

    def test_rollback_restores_library_symlink(self):
        name=upgrade.LIBRARIES[0];library=self.libdir/name;original=self.home/'personal-library.so'
        library.rename(original);library.symlink_to(original)
        def fail_start(root,component,operation,log):
            if operation=='--start' and json.loads((root/'build-info.json').read_text())['display_version']=='1.28-A':
                raise RuntimeError('start failed')
            self.change_process_state(root,component,operation,log)
        self.control.side_effect=fail_start
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.assertTrue(library.is_symlink())
        self.assertEqual(library.readlink(),original)
        self.verify_old()

    def test_git_checkout_and_other_install_root_are_protected(self):
        (self.root/'.git').mkdir()
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        (self.root/'.git').rmdir()
        self.record.write_text(json.dumps({'root':str(self.home/'other')}))
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.mocks[3].assert_not_called()

    def test_concurrent_update_is_rejected(self):
        with upgrade.update_lock(),self.assertRaises(RuntimeError):
            upgrade.install_update(self.result,lambda _:None)
        self.control.assert_not_called();self.verify_old()

    def test_invalid_inventory_is_rejected_before_download_or_stop(self):
        for data in ([], {'root':42}, {'root':str(self.root),'template_hashes':[]}):
            with self.subTest(data=data):
                self.record.write_text(json.dumps(data))
                with self.assertRaises(ValueError):upgrade.install_update(self.result,lambda _:None)
                self.control.assert_not_called();self.mocks[3].assert_not_called()

    def test_update_initializes_missing_state_directory(self):
        shutil.rmtree(self.state)
        upgrade.install_update(self.result,lambda _:None)
        self.assertTrue(self.record.is_file())
        self.assertEqual(json.loads((self.root/'build-info.json').read_text())['display_version'],'1.28-A')

    def test_keyboard_interrupt_during_copy_restores_original(self):
        original=upgrade.atomic_copy;failed=False
        def copy(source,target):
            nonlocal failed
            if target.name=='libadws_panel.so' and not failed:
                failed=True;raise KeyboardInterrupt()
            original(source,target)
        with patch.object(upgrade,'atomic_copy',side_effect=copy), self.assertRaises(KeyboardInterrupt):
            upgrade.install_update(self.result,lambda _:None)
        self.verify_old()

    def test_interrupt_after_old_directory_move_restores_installation(self):
        rename=Path.rename;interrupted=False
        def interrupt_after_move(path,target):
            nonlocal interrupted
            result=rename(path,target)
            if path==self.root and not interrupted:
                interrupted=True;raise KeyboardInterrupt()
            return result
        with patch.object(Path,'rename',interrupt_after_move),self.assertRaises(KeyboardInterrupt):
            upgrade.install_update(self.result,lambda _:None)
        self.verify_old();self.assertEqual(self.active,{'desktop'})

    def test_interrupt_after_new_directory_move_restores_installation(self):
        rename=Path.rename;interrupted=False
        def interrupt_after_move(path,target):
            nonlocal interrupted
            result=rename(path,target)
            if target==self.root and not interrupted:
                interrupted=True;raise KeyboardInterrupt()
            return result
        with patch.object(Path,'rename',interrupt_after_move),self.assertRaises(KeyboardInterrupt):
            upgrade.install_update(self.result,lambda _:None)
        self.verify_old();self.assertEqual(self.active,{'desktop'})

    def test_prebuilt_libraries_are_verified_before_install(self):
        folder=self.root/'prebuilt';folder.mkdir()
        hashes={}
        for name in upgrade.LIBRARIES:
            (folder/name).write_text(name)
            hashes[name]=hashlib.sha256(name.encode()).hexdigest()
        manifest={'version':'1.27-D','os':'arch','arch':'x86_64','sha256':hashes}
        (folder/'manifest.json').write_text(json.dumps(manifest))
        # Restore the real verifier while replacing only external build/ldd calls.
        self.patches[4].stop()
        with (self.home/'build.log').open('ab') as log, patch.object(upgrade,'run'), patch.object(upgrade.shutil,'which',return_value=None):
            self.assertEqual(set(upgrade.prepare_libraries(self.root,True,log)),set(upgrade.LIBRARIES))
            (folder/upgrade.LIBRARIES[0]).write_text('corrupt')
            with self.assertRaises(ValueError):upgrade.prepare_libraries(self.root,True,log)


class NativeSupervisorUpgradeTests(unittest.TestCase):
    def test_prebuilt_runner_is_verified_and_staged_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'src/adws-runtime').mkdir(parents=True)
            (root/'src/adws-runtime/Cargo.toml').touch()
            (root/'src/adws-start-menu').mkdir(parents=True)
            (root/'src/adws-start-menu/Cargo.toml').touch()
            (root/'build-info.json').write_text('{"display_version":"1.35 Development"}')
            folder = root/'prebuilt'; folder.mkdir()
            hashes = {}
            for name in (*upgrade.LIBRARIES, 'adws-plugin-runner', 'adws-start-menu'):
                (folder/name).write_bytes(b'artifact')
                hashes[name] = hashlib.sha256(b'artifact').hexdigest()
            (folder/'manifest.json').write_text(json.dumps({'version':'1.35 Development','os':'arch','arch':'x86_64','sha256':hashes}))
            with patch.object(upgrade, 'run'), patch.object(upgrade.shutil, 'which', return_value=None):
                paths = upgrade.prepare_libraries(root, True, io.BytesIO())
                self.assertEqual(set(paths), set(upgrade.LIBRARIES))
                installed = root/'libexec/adws-plugin-runner'
                self.assertEqual(installed.read_bytes(), b'artifact')
                self.assertEqual(installed.stat().st_mode & 0o777, 0o755)
                self.assertEqual((root/'libexec/adws-start-menu').stat().st_mode & 0o777, 0o755)
                (folder/'adws-start-menu').write_bytes(b'corrupted')
                with self.assertRaises(ValueError): upgrade.prepare_libraries(root, True, io.BytesIO())
                self.assertEqual(installed.read_bytes(), b'artifact')

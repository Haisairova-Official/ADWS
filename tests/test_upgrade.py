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
import mnws_upgrade as upgrade
import mnws_runtime


def archive(path, version='1.28-A'):
    with zipfile.ZipFile(path, 'w') as z:
        files={'build-info.json':json.dumps({'display_version':version}), 'mnws':'#!/bin/sh\nexit 0\n',
               'tools/mnws_runtime.py':'', 'tools/mnws_uninstall.py':'', 'tools/mnws-config.py':'',
               'src/niri-desktop-layer/desktop-layer':'', 'src/niri-desktop-layer/start-desktop-layer':'',
               'config/custom.json':'new default'}
        files.update({'binaries/'+name:'new '+name for name in upgrade.LIBRARIES})
        for name, data in files.items():z.writestr('MNWS/'+name,data)


class ArchiveTests(unittest.TestCase):
    def test_download_proxy_then_direct_and_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            z=Path(folder)/'fixture.zip';archive(z);payload=z.read_bytes()
            checksum=hashlib.sha256(payload).hexdigest()
            with patch.dict(os.environ,{'MNWS_GITHUB_PROXY':'https://ghproxy.example/'}), patch.object(upgrade.urllib.request,'urlopen',side_effect=[io.BytesIO(b'bad proxy'),io.BytesIO(payload)]) as request:
                upgrade.download('https://github.com/a/b.zip',Path(folder)/'download.zip',True,checksum)
                self.assertEqual([c.args[0].full_url for c in request.call_args_list],['https://ghproxy.example/https://github.com/a/b.zip','https://github.com/a/b.zip'])
            with patch.object(upgrade.urllib.request,'urlopen',return_value=io.BytesIO(payload)) as request:
                upgrade.download('https://github.com/a/b.zip',Path(folder)/'direct.zip',False)
                self.assertEqual(request.call_args.args[0].full_url,'https://github.com/a/b.zip')

    def test_unsafe_archives_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for index,name in enumerate(('../escape','/absolute','MNWS/../../escape','MNWS/link')):
                z=root/f'{index}.zip'
                with zipfile.ZipFile(z,'w') as output:
                    info=zipfile.ZipInfo(name)
                    if name.endswith('link'):info.external_attr=(stat.S_IFLNK|0o777)<<16
                    output.writestr(info,'target')
                with self.assertRaises(ValueError):upgrade.extract(z,root/f'out{index}')
            self.assertFalse((root.parent/'escape').exists())

    def test_arch_asset_selection_uses_canonical_repository(self):
        release={'tag_name':'v1.28-A','assets':[{'name':'MNWS1.28-A_for_arch.zip','browser_download_url':'https://evil.invalid','digest':'sha256:'+'a'*64}]}
        with patch.object(upgrade.platform,'freedesktop_os_release',return_value={'ID':'arch'}), patch.object(upgrade.platform,'machine',return_value='x86_64'):
            url,digest,prebuilt=upgrade.package(release)
            self.assertTrue(url.startswith('https://github.com/Haisairova-Official/MNWS/releases/download/v1.28-A/'))
            self.assertEqual(digest,'a'*64);self.assertTrue(prebuilt)
        with patch.object(upgrade.platform,'freedesktop_os_release',return_value={'ID':'ubuntu'}):
            url,digest,prebuilt=upgrade.package(release)
            self.assertTrue(url.endswith('/archive/refs/tags/v1.28-A.zip'));self.assertFalse(prebuilt)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.root=self.home/'installed'
        self.root.mkdir();(self.root/'build-info.json').write_text('{"display_version":"1.27-D"}')
        (self.root/'mnws').write_text('old command')
        for name in upgrade.PRESERVE:
            path=self.root/name;path.mkdir(parents=True,exist_ok=True);(path/'custom.json').write_text('user data')
        self.state=self.home/'state/mnws';self.state.mkdir(parents=True)
        self.record=self.state/'install-record.json'
        self.record.write_text(json.dumps({'root':str(self.root),'configs':['preserve-me'],'libraries':{}}))
        self.libdir=self.home/'.local/lib/waybar';self.libdir.mkdir(parents=True)
        for name in upgrade.LIBRARIES:(self.libdir/name).write_text('old '+name)
        self.source=self.home/'source.zip';archive(self.source)
        self.result={'available':True,'release':{'tag_name':'v1.28-A','prerelease':True},'use_proxy':True}
        self.patches=[patch.dict(os.environ,{'HOME':str(self.home),'XDG_STATE_HOME':str(self.home/'state')}),
                      patch.object(upgrade,'ROOT',self.root),
                      patch.object(upgrade,'package',return_value=('https://github.com/fixture.zip',None,False)),
                      patch.object(upgrade,'download',side_effect=lambda url,target,*args:shutil.copy2(self.source,target)),
                      patch.object(upgrade,'prepare_libraries',return_value={n:Path('binaries')/n for n in upgrade.LIBRARIES}),
                      patch.object(mnws_runtime,'pids',side_effect=lambda component:[123] if component=='desktop' else []),
                      patch.object(upgrade,'control')]
        self.mocks=[p.start() for p in self.patches]
        for p in self.patches:self.addCleanup(p.stop)
        self.control=self.mocks[-1]

    def verify_old(self):
        self.assertEqual((self.root/'mnws').read_text(),'old command')
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
        backup=Path(data['last_update_backup']);self.assertEqual((backup/'source/mnws').read_text(),'old command')
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
            if target.name=='libmnws_panel.so' and not failed:
                failed=True;raise OSError('disk full')
            original(source,target)
        with patch.object(upgrade,'atomic_copy',side_effect=copy), self.assertRaises(RuntimeError):
            upgrade.install_update(self.result,lambda _:None)
        self.verify_old()

    def test_restart_failure_restores_old_version(self):
        def control(root,component,operation,log):
            if operation=='--start' and json.loads((root/'build-info.json').read_text())['display_version']=='1.28-A':
                raise RuntimeError('new component failed')
        self.control.side_effect=control
        with self.assertRaises(RuntimeError):upgrade.install_update(self.result,lambda _:None)
        self.verify_old()
        self.assertEqual(self.control.call_args.args[2],'--start')

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

    def test_keyboard_interrupt_during_copy_restores_original(self):
        original=upgrade.atomic_copy;failed=False
        def copy(source,target):
            nonlocal failed
            if target.name=='libmnws_panel.so' and not failed:
                failed=True;raise KeyboardInterrupt()
            original(source,target)
        with patch.object(upgrade,'atomic_copy',side_effect=copy), self.assertRaises(KeyboardInterrupt):
            upgrade.install_update(self.result,lambda _:None)
        self.verify_old()

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

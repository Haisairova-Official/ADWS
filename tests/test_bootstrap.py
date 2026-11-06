import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import adws_bootstrap as bootstrap


def archive(path, extra=None):
    files={'build-info.json':'{"build_version":"1.36.04"}','adws':'#!/bin/sh\n',
        'install.sh':'#!/bin/sh\nprintf "fixture installer\\n"\n','scripts/adws-install.sh':'#!/bin/sh\n',
        'tools/adws_install_workflow.py':'# fixture\n','tools/adws_runtime.py':'',
        'tools/adws_uninstall.py':'','src/niri-desktop-layer/desktop-layer':'',
        'src/niri-desktop-layer/start-desktop-layer':'','tools/adws-config.py':''}
    with zipfile.ZipFile(path,'w') as output:
        for name,text in files.items():output.writestr('bundle/'+name,text)
        if extra:output.writestr(*extra)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.platform=patch.object(bootstrap,'environment',return_value={'system':'Linux','distro':'arch','architecture':'x86_64','arch_prebuilt':True})
        self.platform.start();self.addCleanup(self.platform.stop)
        self.env=patch.dict(os.environ,{'ADWS_GITHUB_PROXY':'','HTTPS_PROXY':'','https_proxy':'','ALL_PROXY':'','all_proxy':''})
        self.env.start();self.addCleanup(self.env.stop)

    def test_release_uses_canonical_asset_url_and_published_digest(self):
        release={'tag_name':'1.36-D','assets':[{'name':'ADWS1.36-D_for_arch.zip','digest':'sha256:'+'a'*64,'browser_download_url':'https://evil.invalid'}]}
        with patch.object(bootstrap,'read_json',return_value=release),patch('adws_upgrade.platform.freedesktop_os_release',return_value={'ID':'arch'}),patch('adws_upgrade.platform.machine',return_value='x86_64'):
            plan=bootstrap.release_plan('1.36-D')
        self.assertEqual(plan['sha256'],'a'*64)
        self.assertTrue(plan['url'].startswith('https://github.com/Haisairova-Official/ADWS/releases/download/'))
        self.assertNotIn('evil.invalid',plan['url'])

    def test_source_is_explicit_and_needs_trusted_checksum(self):
        with patch.object(bootstrap,'read_json',return_value={'tag_name':'1.36-D','assets':[]}),patch('adws_upgrade.platform.freedesktop_os_release',return_value={'ID':'ubuntu'}):
            with self.assertRaisesRegex(ValueError,'--source'):bootstrap.release_plan()
            with self.assertRaisesRegex(ValueError,'checksum'):bootstrap.release_plan(source=True)
            plan=bootstrap.release_plan(source=True,sha256='b'*64)
            self.assertTrue(plan['source']);self.assertIn('/archive/refs/tags/',plan['url'])

    def test_mirror_is_locale_gated_and_preserves_configured_proxy(self):
        with patch.object(bootstrap,'chinese',return_value=False):
            with self.assertRaises(ValueError):bootstrap.transfer_url('https://github.com/a','https://mirror.test')
        with patch.object(bootstrap,'chinese',return_value=True),patch.dict(os.environ,{'ADWS_GITHUB_PROXY':'https://old.test'}):
            with self.assertRaisesRegex(ValueError,'existing'):bootstrap.transfer_url('https://github.com/a','https://new.test')
            self.assertEqual(bootstrap.transfer_url('https://github.com/a'),'https://old.test/https://github.com/a')

    def test_prepare_keeps_verified_source_for_resume_and_refuses_changed_entrypoint(self):
        source=self.root/'fixture.zip';digest=archive(source)
        plan=bootstrap.artifact_plan('https://example.test/fixture.zip',digest,source=True)
        def transfer(url,target,sha,**kw):shutil.copy2(source,target)
        destination=bootstrap.prepare(plan,cache=self.root/'cache',transfer=transfer)
        self.assertTrue((destination/'install.sh').exists())
        self.assertEqual(bootstrap.prepare(plan,cache=self.root/'cache',transfer=transfer),destination)
        (destination/'install.sh').write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):bootstrap.prepare(plan,cache=self.root/'cache',transfer=transfer)

    def test_cached_source_resource_is_verified_even_if_not_an_entrypoint(self):
        source=self.root/'fixture.zip';digest=archive(source)
        plan=bootstrap.artifact_plan('https://example.test/fixture.zip',digest,source=True)
        def transfer(url,target,sha,**kwargs):shutil.copy2(source,target)
        destination=bootstrap.prepare(plan,cache=self.root/'cache',transfer=transfer)
        generated=destination/'src/native/target/release';generated.mkdir(parents=True)
        (generated/'binary').write_bytes(b'allowed build output')
        self.assertEqual(bootstrap.prepare(plan,cache=self.root/'cache',transfer=transfer),destination)
        (destination/'tools/adws_runtime.py').write_text('changed helper')
        marker=destination/'.adws-bootstrap.json';saved=json.loads(marker.read_text())
        saved['entrypoint_hashes']={}
        marker.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError,'resource changed'):bootstrap.prepare(plan,cache=self.root/'cache',transfer=transfer)

    def test_existing_user_directory_and_bad_checksum_never_execute(self):
        source=self.root/'fixture.zip';digest=archive(source)
        plan=bootstrap.artifact_plan('https://example.test/fixture.zip',digest,source=True)
        existing=self.root/'personal';existing.mkdir();(existing/'keep').write_text('personal')
        def transfer(url,target,sha,**kw):shutil.copy2(source,target)
        with self.assertRaisesRegex(ValueError,'already exists'):
            bootstrap.prepare(plan,cache=self.root/'cache',destination=existing,transfer=transfer)
        self.assertEqual((existing/'keep').read_text(),'personal')
        with patch.object(bootstrap,'prepare',side_effect=ValueError('wrong checksum')),patch.object(bootstrap.subprocess,'run') as run,patch.object(bootstrap.os,'geteuid',return_value=1000):
            with self.assertRaises(ValueError):bootstrap.main(['--url',plan['url'],'--sha256',digest,'--source','--yes'])
        run.assert_not_called()

    def test_traversal_and_symlinks_rejected_in_fresh_staging(self):
        for index,extra in enumerate([('../escape','bad'),(self.symlink(),'outside')]):
            source=self.root/f'bad{index}.zip';digest=archive(source,extra)
            plan=bootstrap.artifact_plan('https://example.test/bad.zip',digest,source=True)
            def transfer(url,target,sha,**kw):shutil.copy2(source,target)
            with self.assertRaises(ValueError):bootstrap.prepare(plan,cache=self.root/f'cache{index}',transfer=transfer)
            self.assertFalse((self.root/'escape').exists())
    @staticmethod
    def symlink():
        info=zipfile.ZipInfo('bundle/evil');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;return info

    def test_entry_forwards_mode_and_resume_without_running_as_root(self):
        with patch.object(bootstrap.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(ValueError,'desktop user'):bootstrap.main(['--plan'])
        with patch.object(bootstrap.os,'geteuid',return_value=1000),patch.object(bootstrap,'prepare',return_value=self.root),patch.object(bootstrap.subprocess,'run',return_value=subprocess.CompletedProcess([],2)) as run:
            code=bootstrap.main(['--url','https://example.test/a.zip','--sha256','a'*64,'--source','--yes','--','--mode','fresh','--resume'])
        self.assertEqual(code,2)
        self.assertEqual(run.call_args.args[0],['bash',str(self.root/'install.sh'),'--build-fallback','--mode','fresh','--resume'])

    def test_unattended_requires_explicit_download_confirmation(self):
        with patch.object(bootstrap.os,'geteuid',return_value=1000),patch.object(bootstrap.sys.stdin,'isatty',return_value=False),patch.object(bootstrap,'prepare') as prepare:
            with self.assertRaisesRegex(ValueError,'--yes'):bootstrap.main(['--url','https://example.test/a.zip','--sha256','a'*64,'--source'])
            prepare.assert_not_called()

    def test_standalone_zipapp_help_works_without_checkout(self):
        spec=importlib.util.spec_from_file_location('package_bootstrap_fixture',ROOT/'scripts/package-bootstrap.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        target=module.build(self.root/'standalone.pyz')
        # No PYTHONPATH; the zipapp unpacks only its own bundled runtime modules.
        result=subprocess.run([sys.executable,'-I',str(target),'--help'],cwd=self.root,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--sha256',result.stdout);self.assertIn('--release',result.stdout)
        self.assertTrue(target.with_suffix('.pyz.sha256').is_file())

if __name__=='__main__':unittest.main()

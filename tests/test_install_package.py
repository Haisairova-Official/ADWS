import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import adws_install_package as package


class InstallPackageTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='adws-package-test-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for name in package.REQUIRED:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('')
        (self.root/'tools/adws_fonts.py').write_text("URL='https://example.test/fonts.zip'\nSHA256='"+'a'*64+"'\n")

    def test_missing_required_installer_file_blocks_payload(self):
        self.assertTrue(package.check(self.root)['complete'])
        (self.root/'tools/adws_install_workflow.py').unlink()
        report=package.check(self.root)
        self.assertFalse(report['complete'])
        self.assertTrue(any('adws_install_workflow.py' in e for e in report['errors']))

    def test_unstaged_installer_helpers_are_explicit_additions(self):
        extra=self.root/'tools/adws_install_future.py';extra.write_text('')
        additions=package.packaging_additions(self.root)
        self.assertIn('tools/adws_install_future.py',additions)
        self.assertIn('docs/installer-roadmap.md',additions)

    def test_missing_static_import_is_reported_without_execution(self):
        (self.root/'tools/adws_setup.py').write_text('import adws_not_packaged\nraise RuntimeError("must not execute")\n')
        report=package.check(self.root)
        self.assertTrue(any('adws_not_packaged.py' in e for e in report['errors']))

    def test_bar_assets_and_includes_must_ship(self):
        (self.root/'config/waybar/style-top.css').write_text('@import "missing.css"; box { background-image: url("missing.svg"); }')
        (self.root/'config/waybar/config-top.jsonc').write_text('{"include":["missing.jsonc"]}')
        errors='\n'.join(package.check(self.root)['errors'])
        for name in ('missing.css','missing.svg','missing.jsonc'):self.assertIn(name,errors)

    def test_reference_outside_archive_rejected(self):
        (self.root/'config/waybar/style-top.css').write_text('box { background-image: url("/etc/passwd"); }')
        errors=package.check(self.root)['errors']
        self.assertTrue(any('escapes package' in e for e in errors))

    def test_font_download_needs_checksum(self):
        (self.root/'tools/adws_fonts.py').write_text("URL='https://example.test/fonts.zip'\n")
        self.assertFalse(package.check(self.root)['complete'])

    def test_prebuilt_library_and_executable_hashes_verified(self):
        prebuilt=self.root/'prebuilt';prebuilt.mkdir();hashes={}
        for name in package.NATIVE:
            content=('fixture '+name).encode();(prebuilt/name).write_bytes(content)
            hashes[name]=hashlib.sha256(content).hexdigest()
        (prebuilt/'manifest.json').write_text(json.dumps({'sha256':hashes}))
        self.assertTrue(package.check(self.root,require_prebuilt=True)['complete'])
        (prebuilt/package.NATIVE[0]).write_bytes(b'corrupt')
        report=package.check(self.root,require_prebuilt=True)
        self.assertFalse(report['complete'])
        self.assertIn('checksum mismatch','\n'.join(report['errors']))

    def test_incomplete_source_stops_release_before_compilation(self):
        spec=importlib.util.spec_from_file_location('adws_package_arch_test',ROOT/'scripts/package-arch.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        (self.root/'build-info.json').write_text('{"major_version":"1.36"}')
        (self.root/'tools/adws_install_workflow.py').unlink()
        with patch.object(module,'ROOT',self.root),patch.object(sys,'argv',['package-arch.py']),patch.object(module.platform,'machine',return_value='x86_64'),patch.object(module.platform,'freedesktop_os_release',return_value={'ID':'arch'}),patch.object(module.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'Incomplete ADWS package'):module.main()
        run.assert_not_called()

    def test_current_source_has_complete_static_payload(self):
        report=package.check(ROOT)
        self.assertEqual(report['errors'],[])
        self.assertIn('target distro library ABI',report['not_verified'])


if __name__=='__main__':unittest.main()

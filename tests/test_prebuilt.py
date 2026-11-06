import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_prebuilt as prebuilt
from adws_setup import atomic_install


class PrebuiltTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'prebuilt'
        self.folder.mkdir()
        self.host = patch.object(prebuilt.platform, 'freedesktop_os_release', return_value={'ID': 'arch'})
        self.machine = patch.object(prebuilt.platform, 'machine', return_value='x86_64')
        self.host.start(); self.machine.start()
        self.addCleanup(self.host.stop); self.addCleanup(self.machine.stop)
        self.env = patch.dict(os.environ, {'ADWS_INSTALL_MANAGED': ''})
        self.env.start(); self.addCleanup(self.env.stop)

    def bundle(self, data=b'placeholder'):
        for name in prebuilt.NAMES:
            (self.folder / name).write_bytes(data)
        self.manifest()

    def manifest(self):
        (self.folder / 'manifest.json').write_text(json.dumps({
            'os': 'arch', 'arch': 'x86_64',
            'sha256': {name: hashlib.sha256((self.folder / name).read_bytes()).hexdigest() for name in prebuilt.NAMES}
        }))

    def compile(self, text, output, shared=False, extra=()):
        compiler = shutil.which('cc')
        if not compiler or prebuilt.platform.machine() != 'x86_64' or not prebuilt._system_loader():
            self.skipTest('ELF fixture compiler/loader not available')
        source = self.root / (output.name + '.c')
        source.write_text(text)
        subprocess.run([compiler, *(['-shared', '-fPIC'] if shared else []), str(source), '-o', str(output), *extra], check=True, capture_output=True)

    def elf_bundle(self):
        marker = self.root / 'main-or-constructor-ran'
        source = '#include <stdio.h>\n' + \
                 f'static void mark(void){{FILE*f=fopen("{marker}","w");if(f)fclose(f);}}\n' + \
                 '__attribute__((constructor)) static void constructor(void){mark();}\nint main(void){mark();return 0;}\n'
        executable = self.root / 'sample'
        library = self.root / 'sample.so'
        self.compile(source, executable)
        self.compile(source, library, shared=True)
        for name in prebuilt.NAMES:
            shutil.copy2(library if name.endswith('.so') else executable, self.folder / name)
        self.manifest()
        return marker

    def test_verified_install_and_corruption(self):
        self.bundle()
        compatible = Mock(return_value={'compatible': True})
        confirm = Mock(return_value=True)
        self.assertTrue(prebuilt.install(self.root, self.root / 'lib', confirm, atomic_install, compatibility_checker=compatible))
        self.assertEqual((self.root / 'lib' / prebuilt.NAMES[0]).read_bytes(), b'placeholder')
        executable = self.root / 'libexec/adws-plugin-runner'
        self.assertEqual(executable.stat().st_mode & 0o777, 0o755)
        (self.folder / 'adws-plugin-runner').write_bytes(b'bad')
        writer = Mock()
        with patch.object(prebuilt, '_fallback_approved', return_value=True), self.assertRaises(prebuilt.PrebuiltIntegrityError):
            prebuilt.install(self.root, self.root / 'lib', confirm, writer, compatibility_checker=compatible)
        writer.assert_not_called()
        self.assertEqual(compatible.call_count, 1)

    def test_source_install_unchanged(self):
        self.folder.rmdir()
        self.assertFalse(prebuilt.install(self.root, self.root, Mock(), Mock()))

    def test_incomplete_prebuilt_folder_is_corruption_not_source_fallback(self):
        with patch.object(prebuilt, '_fallback_approved', return_value=True), self.assertRaises(prebuilt.PrebuiltIntegrityError):
            prebuilt.install(self.root, self.root, Mock(), Mock())

    def test_integrity_checked_before_platform_or_fallback(self):
        self.bundle()
        (self.folder / prebuilt.NAMES[0]).unlink()
        with patch.object(prebuilt.platform, 'freedesktop_os_release', return_value={'ID': 'debian'}), \
             patch.object(prebuilt, '_fallback_approved', return_value=True), self.assertRaises(prebuilt.PrebuiltIntegrityError):
            prebuilt.inspect_compatibility(self.root)

    def test_invalid_elf_is_not_downgraded_to_source_build(self):
        self.bundle(b'checksum matches but not an executable')
        with patch.object(prebuilt, '_fallback_approved', return_value=True), self.assertRaises(prebuilt.PrebuiltIntegrityError):
            prebuilt.install(self.root, self.root, Mock(), Mock())

    def test_safe_loader_checks_never_execute_main_or_constructors(self):
        marker = self.elf_bundle()
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.run(argv, **kwargs)
        with patch.dict(os.environ, {'LD_PRELOAD': '/does/not/exist', 'LD_AUDIT': '/untrusted/audit.so'}):
            report = prebuilt.inspect_compatibility(self.root, runner=run)
        self.assertEqual(report['errors'], [])
        self.assertTrue(report['compatible'])
        self.assertEqual(len(report['components']), len(prebuilt.NAMES))
        self.assertFalse(marker.exists())
        self.assertTrue(all(argv[1] == '--list' for argv, _ in calls))
        self.assertTrue(all('LD_PRELOAD' not in args['env'] and 'LD_AUDIT' not in args['env'] for _, args in calls))

    def test_nonversioned_missing_gtk_style_symbol_is_caught_statically(self):
        self.elf_bundle()
        self.compile('extern int adws_required_new_api(void); int use(void){return adws_required_new_api();}\n',
                     self.folder / prebuilt.NAMES[0], shared=True)
        self.manifest()
        report = prebuilt.inspect_compatibility(self.root)
        self.assertFalse(report['compatible'])
        error = next(row for row in report['errors'] if row['component'] == prebuilt.NAMES[0])
        self.assertEqual(error['kind'], 'missing-symbols')
        self.assertIn('adws_required_new_api', error['detail'])

    def test_version_failure_is_reported_and_no_copy_without_approval(self):
        self.elf_bundle()
        runner = Mock(return_value=Mock(returncode=1, stdout='', stderr="version `GLIBC_2.99' not found (required by libniri_taskbar.so)"))
        report = prebuilt.inspect_compatibility(self.root, runner=runner)
        self.assertIn('GLIBC_2.99', report['errors'][0]['detail'])
        writer = Mock(); confirm = Mock()
        with self.assertRaisesRegex(RuntimeError, 'GLIBC_2.99'):
            prebuilt.install(self.root, self.root / 'lib', confirm, writer, compatibility_checker=lambda _: report)
        confirm.assert_not_called(); writer.assert_not_called()

    def test_only_explicit_managed_approval_can_fallback(self):
        self.bundle()
        report = {'compatible': False, 'errors': [{'component': 'adws-start-menu', 'detail': 'missing libgtk-3.so.0'}]}
        writer = Mock(); confirm = Mock()
        with patch.dict(os.environ, {'ADWS_INSTALL_MANAGED': '1'}), \
             patch('adws_install_workflow.approved_plan', return_value={'build_fallback': True}):
            self.assertFalse(prebuilt.install(self.root, self.root / 'lib', confirm, writer, compatibility_checker=lambda _: report))
        confirm.assert_not_called(); writer.assert_not_called()
        with patch.dict(os.environ, {'ADWS_INSTALL_MANAGED': '1'}), \
             patch('adws_install_workflow.approved_plan', return_value={'build_fallback': False}), self.assertRaises(RuntimeError):
            prebuilt.install(self.root, self.root / 'lib', confirm, writer, compatibility_checker=lambda _: report)

    def test_confirm_time_changes_rechecked_before_first_write(self):
        self.bundle()
        def confirm(_):
            (self.folder / prebuilt.NAMES[-1]).write_bytes(b'modified while dialog open')
            return True
        writer = Mock()
        with self.assertRaises(prebuilt.PrebuiltIntegrityError):
            prebuilt.install(self.root, self.root / 'lib', confirm, writer, compatibility_checker=lambda _: {'compatible': True})
        writer.assert_not_called()

    def test_symlinked_artifact_never_installed(self):
        self.bundle()
        original = self.folder / prebuilt.NAMES[0]
        elsewhere = self.root / 'outside'
        original.rename(elsewhere); original.symlink_to(elsewhere)
        with self.assertRaises(prebuilt.PrebuiltIntegrityError):
            prebuilt.verify_artifacts(self.root)

    def test_timeout_or_missing_loader_blocks_instead_of_assuming_compatibility(self):
        self.elf_bundle()
        with patch.object(prebuilt, '_system_loader', return_value=None):
            report = prebuilt.inspect_compatibility(self.root)
        self.assertEqual(report['status'], 'unverified')
        self.assertFalse(report['compatible'])
        report = prebuilt.inspect_compatibility(self.root, runner=Mock(side_effect=subprocess.TimeoutExpired('loader', 20)))
        self.assertFalse(report['compatible'])
        self.assertTrue(all(row['kind'] == 'loader-check' for row in report['errors']))

    def test_unknown_interpreter_is_never_executed(self):
        self.elf_bundle()
        self.compile('int main(void){return 0;}\n', self.folder / 'adws-start-menu', extra=('-Wl,--dynamic-linker=/tmp/untrusted-loader',))
        self.manifest()
        report = prebuilt.inspect_compatibility(self.root)
        self.assertFalse(report['compatible'])
        self.assertTrue(any(row['kind'] == 'interpreter' for row in report['errors']))

    def test_new_versioned_symbol_cannot_bind_to_older_provider(self):
        self.elf_bundle()
        provider = self.root / 'libadws-test-abi.so'
        version = self.root / 'abi.map'
        version.write_text('ADWS_2.0 {global: adws_new_api; local: *;};\n')
        self.compile('int adws_new_api(void){return 0;}\n', provider, shared=True,
                     extra=('-Wl,-soname,libadws-test-abi.so', '-Wl,--version-script=' + str(version)))
        consumer = self.folder / prebuilt.NAMES[0]
        self.compile('extern int adws_new_api(void); int call_api(void){return adws_new_api();}\n', consumer, shared=True,
                     extra=('-L' + str(self.root), '-ladws-test-abi'))
        self.manifest()
        # Simulate a loader which inventories the libraries but does not report
        # version failures. The static symbol check must still reject ABI 1.
        def run(argv, **kwargs):
            if Path(argv[-1]) == consumer:
                return Mock(returncode=0, stdout=f'libadws-test-abi.so => {provider} (0x123456)\n', stderr='')
            return subprocess.run(argv, **kwargs)
        self.assertTrue(prebuilt.inspect_compatibility(self.root, runner=run)['compatible'])
        version.write_text('ADWS_1.0 {global: adws_new_api; local: *;};\n')
        self.compile('int adws_new_api(void){return 0;}\n', provider, shared=True,
                     extra=('-Wl,-soname,libadws-test-abi.so', '-Wl,--version-script=' + str(version)))
        report = prebuilt.inspect_compatibility(self.root, runner=run)
        self.assertFalse(report['compatible'])
        self.assertIn('adws_new_api@ADWS_2.0', str(report['errors']))

    def test_relocation_dependent_rpath_does_not_pass_at_wrong_location(self):
        self.elf_bundle()
        self.compile('int main(void){return 0;}\n', self.folder / 'adws-start-menu',
                     extra=('-Wl,-rpath,$ORIGIN/private-libs',))
        self.manifest()
        report = prebuilt.inspect_compatibility(self.root)
        self.assertFalse(report['compatible'])
        self.assertTrue(any(row['kind'] == 'relocation-path' for row in report['errors']))

    def test_whole_build_change_during_confirmation_invalidates_review(self):
        self.bundle()
        def confirm(_):
            self.bundle(b'newly replaced release, with its own matching manifest')
            return True
        writer = Mock()
        with self.assertRaisesRegex(prebuilt.PrebuiltIntegrityError, 'manifest changed'):
            prebuilt.install(self.root, self.root / 'lib', confirm, writer,
                             compatibility_checker=lambda _: {'compatible': True})
        writer.assert_not_called()

    def test_staging_prevents_mid_copy_source_build_mixture(self):
        self.bundle()
        copied = []
        def writer(source, destination, **kwargs):
            copied.append(source.read_bytes())
            if len(copied) == 1:
                self.bundle(b'different source revision')
            atomic_install(source, destination, **kwargs)
        self.assertTrue(prebuilt.install(self.root, self.root / 'lib', lambda _: True, writer,
                                         compatibility_checker=lambda _: {'compatible': True}))
        self.assertEqual(copied, [b'placeholder'] * len(prebuilt.NAMES))

    def test_versioned_symbol_inventory_parses_real_system_libraries(self):
        loader = prebuilt._system_loader()
        if not loader:
            self.skipTest('No system loader')
        data = prebuilt.elf_metadata(loader)
        self.assertTrue(any(version for _, version in data['exported']))
        self.assertFalse(data['required'])


if __name__ == '__main__':
    unittest.main()

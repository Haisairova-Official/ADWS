import copy
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_boot_themes as themes


class BootThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'system'
        self.root.mkdir()
        self.backup = self.base / 'backup'
        self.runner = Mock(return_value=Mock(returncode=0))

    def write(self, path, data):
        actual = self.root / path.lstrip('/')
        actual.parent.mkdir(parents=True, exist_ok=True)
        actual.write_bytes(data.encode() if isinstance(data, str) else data)
        return actual

    def login(self, manager='sddm'):
        alias = self.root / 'etc/systemd/system/display-manager.service'
        alias.parent.mkdir(parents=True, exist_ok=True)
        alias.symlink_to('/usr/lib/systemd/system/' + manager + '.service')
        self.write('/usr/share/sddm/themes/adws/Main.qml', 'import QtQuick 2.0\nItem {}\n')
        self.write('/usr/share/sddm/themes/adws/metadata.desktop', '[SddmGreeterTheme]\nName=ADWS\n')

    def plymouth(self):
        self.write('/usr/bin/plymouth', b'fake-plymouth')
        self.write('/usr/bin/mkinitcpio', b'fake-mkinitcpio')
        self.write('/usr/lib/plymouth/script.so', b'fake-library')
        self.write('/usr/share/plymouth/themes/adws/adws.plymouth',
                   '[Plymouth Theme]\nName=ADWS\nModuleName=script\n')
        self.write('/usr/share/plymouth/themes/adws/adws.script', 'sprite = Sprite();\n')
        self.write('/etc/mkinitcpio.conf', 'HOOKS=(base systemd autodetect plymouth modconf block filesystems fsck)\n')
        self.write('/etc/mkinitcpio.d/linux.preset',
                   'ALL_config="/etc/mkinitcpio.conf"\nALL_kver="/boot/vmlinuz-linux"\n'
                   "PRESETS=('default' 'fallback')\n"
                   'default_image="/boot/initramfs-linux.img"\n'
                   'fallback_image="/boot/initramfs-linux-fallback.img"\n'
                   'fallback_options="-S autodetect"\n')
        self.write('/boot/vmlinuz-linux', b'kernel')
        self.write('/boot/initramfs-linux.img', b'original initrd')
        self.write('/boot/initramfs-linux-fallback.img', b'original fallback')
        self.write('/etc/plymouth/plymouthd.conf', '# User comment\n[Daemon]\nTheme=old\nShowDelay=2\n')
        self.write('/etc/kernel/cmdline', 'quiet splash root=UUID=example\n')
        self.write('/boot/loader/loader.conf', 'default linux.conf\n')

    def plan(self, **kwargs):
        return themes.plan(root=self.root, runner=self.runner, **kwargs)

    def rebuild(self, argv, **kwargs):
        self.assertEqual(argv[:3], ['/usr/bin/mkinitcpio', '--nopost', '--preset'])
        preset=Path(argv[3]);self.assertTrue(preset.is_relative_to(self.backup/'rebuild'))
        self.assertTrue(kwargs['check'])
        values=dict(line.split('=',1) for line in preset.read_text().splitlines() if '=' in line)
        Path(themes._literal(values['default_image'])).write_bytes(b'new initrd')
        Path(themes._literal(values['fallback_image'])).write_bytes(b'new fallback')
        return Mock(returncode=0)

    def test_preserve_is_read_only_no_privilege_commands_or_backup(self):
        self.login('gdm')
        before = sorted(str(p) for p in self.root.rglob('*'))
        proposal = self.plan()
        self.assertEqual(proposal['status'], 'preserved')
        self.assertEqual(proposal['changes'], [])
        with patch.object(os, 'geteuid', return_value=1000):
            result = themes.apply(proposal, self.backup)
        self.assertEqual(result['status'], 'preserved')
        self.runner.assert_not_called()
        self.assertFalse(self.backup.exists())
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))

    def test_selected_manager_distinct_from_installed_theme(self):
        self.login('plasmalogin')
        report = themes.detect(self.root)
        self.assertEqual(report['login_manager']['id'], 'plasmalogin')
        self.assertEqual(report['sddm']['themes'], ['adws'])
        proposal = self.plan(login_theme='adws')
        self.assertTrue(proposal['unsupported'])
        self.assertFalse(proposal['changes'])
        self.assertFalse(proposal['commands'])

    def test_sddm_apply_and_rollback_only_managed_fragment(self):
        self.login()
        main = self.write('/etc/sddm.conf', '[General]\nDisplayServer=wayland\n')
        original = main.read_bytes()
        proposal = self.plan(login_theme='adws')
        self.assertEqual(proposal['conflicts'], [])
        result = themes.apply(proposal, self.backup, runner=self.runner)
        managed = self.root / 'etc/sddm.conf.d/99-adws-theme.conf'
        self.assertIn('Current=adws', managed.read_text())
        self.assertEqual(main.read_bytes(), original)
        self.runner.assert_not_called()
        self.assertEqual(result['verification']['login'], 'pending-next-login')
        self.assertEqual(json.loads((self.backup / 'journal.json').read_text())['result'], result)
        rollback = themes.rollback(self.backup)
        self.assertEqual(rollback['status'], 'rolled-back')
        self.assertFalse(managed.exists())
        self.assertEqual(main.read_bytes(), original)

    def test_sddm_user_override_is_never_replaced(self):
        self.login()
        main = self.write('/etc/sddm.conf', '[Theme]\nCurrent=mine\n')
        proposal = self.plan(login_theme='adws')
        self.assertIn('overrides', ' '.join(proposal['conflicts']))
        self.assertEqual(main.read_text(), '[Theme]\nCurrent=mine\n')
        main.unlink()
        self.write('/etc/sddm.conf.d/zzz-user.conf', '[Theme]\nCurrent=mine\n')
        self.assertIn('later', ' '.join(self.plan(login_theme='adws')['conflicts']))

    def test_unknown_owned_fragment_is_conflict(self):
        self.login()
        self.write('/etc/sddm.conf.d/99-adws-theme.conf', '[Theme]\nCurrent=mine\n')
        self.assertIn('occupied', ' '.join(self.plan(login_theme='adws')['conflicts']))

    def test_plymouth_pipeline_and_artifact_backup_rollback(self):
        self.plymouth()
        proposal = self.plan(boot_theme='adws')
        self.assertEqual(proposal['conflicts'], [])
        self.assertEqual(proposal['detected']['bootloader']['active'], 'unknown')
        self.assertEqual(proposal['detected']['bootloader']['candidates'], ['systemd-boot'])
        self.assertEqual(len(proposal['artifacts']), 2)
        result = themes.apply(proposal, self.backup, runner=self.rebuild)
        config = self.root / 'etc/plymouth/plymouthd.conf'
        self.assertIn('Theme=adws', config.read_text())
        self.assertIn('# User comment', config.read_text())
        self.assertIn('ShowDelay=2', config.read_text())
        self.assertEqual(result['verification']['boot'], 'pending-next-reboot')
        themes.rollback(self.backup)
        self.assertIn('Theme=old', config.read_text())
        self.assertEqual((self.root / 'boot/initramfs-linux.img').read_bytes(), b'original initrd')
        self.assertEqual((self.root / 'boot/initramfs-linux-fallback.img').read_bytes(), b'original fallback')
        self.assertEqual((self.root / 'boot/loader/loader.conf').read_text(), 'default linux.conf\n')

    def test_rebuild_failure_rolls_back_written_images_and_config(self):
        self.plymouth()
        def failure(argv, **kwargs):
            self.rebuild(argv, **kwargs)
            raise subprocess.CalledProcessError(1, argv)
        with self.assertRaises(subprocess.CalledProcessError):
            themes.apply(self.plan(boot_theme='adws'), self.backup, runner=failure)
        self.assertEqual((self.root / 'boot/initramfs-linux.img').read_bytes(), b'original initrd')
        self.assertIn('Theme=old', (self.root / 'etc/plymouth/plymouthd.conf').read_text())
        self.assertEqual(json.loads((self.backup / 'journal.json').read_text())['status'], 'rolled-back')

    def test_later_user_edits_survive_rollback(self):
        self.plymouth()
        themes.apply(self.plan(boot_theme='adws'), self.backup, runner=self.rebuild)
        image = self.write('/boot/initramfs-linux.img', b'new kernel transaction image')
        config = self.write('/etc/plymouth/plymouthd.conf', '[Daemon]\nTheme=user-after\n')
        result = themes.rollback(self.backup)
        self.assertEqual(result['status'], 'rollback-conflicts')
        self.assertEqual(len(result['conflicts']), 2)
        self.assertEqual(image.read_bytes(), b'new kernel transaction image')
        self.assertIn('user-after', config.read_text())

    def test_config_edited_during_rebuild_is_not_claimed_as_ours(self):
        self.plymouth()
        def race(argv, **kwargs):
            self.rebuild(argv, **kwargs)
            self.write('/etc/plymouth/plymouthd.conf', '[Daemon]\nTheme=other-admin\n')
            return Mock(returncode=0)
        with self.assertRaisesRegex(RuntimeError, 'rollback needs attention'):
            themes.apply(self.plan(boot_theme='adws'), self.backup, runner=race)
        self.assertIn('other-admin', (self.root / 'etc/plymouth/plymouthd.conf').read_text())

    def test_rollback_copy_preserves_edit_made_while_copying_backup(self):
        self.plymouth();themes.apply(self.plan(boot_theme='adws'),self.backup,runner=self.rebuild)
        image=self.root/'boot/initramfs-linux.img';copy2=themes.shutil.copy2
        def concurrent(source,target,*args,**kwargs):
            result=copy2(source,target,*args,**kwargs)
            if Path(source)==self.backup/'1.original' and Path(target).name.startswith('.adws-restore-'):
                image.write_bytes(b'edited during rollback copy')
            return result
        with patch.object(themes.shutil,'copy2',side_effect=concurrent):result=themes.rollback(self.backup)
        self.assertTrue(result['conflicts']);self.assertEqual(image.read_bytes(),b'edited during rollback copy')

    def test_image_edited_during_rebuild_is_not_claimed_as_ours(self):
        self.plymouth()
        def race(argv, **kwargs):
            self.rebuild(argv, **kwargs)
            self.write('/boot/initramfs-linux.img', b'other administrator image')
            return Mock(returncode=0)
        with self.assertRaisesRegex(RuntimeError, 'rollback needs attention'):
            themes.apply(self.plan(boot_theme='adws'),self.backup,runner=race)
        self.assertEqual((self.root/'boot/initramfs-linux.img').read_bytes(),b'other administrator image')
        self.assertEqual((self.root/'boot/initramfs-linux-fallback.img').read_bytes(),b'original fallback')
        self.assertIn('Theme=old',(self.root/'etc/plymouth/plymouthd.conf').read_text())

    def test_sigterm_stops_rebuild_tree_then_restores_config_without_touching_images(self):
        self.plymouth();proposal=self.plan(boot_theme='adws')
        path=self.base/'proposal.json';path.write_text(json.dumps(proposal))
        ready=self.base/'ready';writer=self.base/'writer'
        writer_script=self.base/'writer.py'
        writer_script.write_text('import pathlib,signal,sys,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\np=pathlib.Path(sys.argv[1]);pathlib.Path(sys.argv[2]).touch()\nwhile True:\n p.write_text(str(time.time()))\n time.sleep(.02)\n')
        worker=self.base/'worker.py'
        worker.write_text('''import json, pathlib, sys
sys.path.insert(0,sys.argv[1])
import adws_install_boot_themes as themes
proposal=json.loads(pathlib.Path(sys.argv[2]).read_text())
def rebuild(command,**kwargs):
    return themes._run_rebuild([sys.executable,sys.argv[6],sys.argv[5],sys.argv[4]],**kwargs)
try:
    with themes._cancellation_signals():themes.apply(proposal,pathlib.Path(sys.argv[3]),runner=rebuild)
except KeyboardInterrupt:raise SystemExit(130)
''')
        process=subprocess.Popen([sys.executable,str(worker),str(Path(themes.__file__).parent),str(path),str(self.backup),str(ready),str(writer),str(writer_script)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.addCleanup(lambda:process.kill() if process.poll() is None else None)
        deadline=time.monotonic()+5
        while not ready.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        if not ready.exists():
            process.kill();_,stderr=process.communicate();self.fail(stderr.decode())
        process.send_signal(signal.SIGTERM);_,stderr=process.communicate(timeout=12)
        self.assertEqual(process.returncode,130,stderr.decode())
        last=writer.read_bytes();time.sleep(.12);self.assertEqual(writer.read_bytes(),last)
        self.assertIn('Theme=old',(self.root/'etc/plymouth/plymouthd.conf').read_text())
        self.assertEqual((self.root/'boot/initramfs-linux.img').read_bytes(),b'original initrd')
        self.assertEqual(json.loads((self.backup/'journal.json').read_text())['status'],'rolled-back')

    def test_stale_source_config_and_theme_rejected_before_write(self):
        self.plymouth()
        proposal = self.plan(boot_theme='adws')
        self.write('/usr/share/plymouth/themes/adws/adws.script', 'changed after review')
        with self.assertRaisesRegex(ValueError, 'changed after theme review'):
            themes.apply(proposal, self.backup, runner=self.runner)
        self.assertFalse(self.backup.exists())
        self.runner.assert_not_called()

    def test_arbitrary_commands_and_config_paths_cannot_enter_apply(self):
        self.login()
        for key, value in [('commands', [['/bin/sh', '-c', 'evil']]),
                           ('changes', [{'path': '/etc/passwd', 'before': None, 'content': 'bad'}])]:
            proposal = self.plan(login_theme='adws')
            proposal[key] = value
            with self.assertRaises(ValueError):
                themes.apply(proposal, self.backup, runner=self.runner)
        self.runner.assert_not_called()
        self.assertFalse(self.backup.exists())

    def test_no_fixture_root_can_execute_host_rebuild_by_default(self):
        self.plymouth()
        with self.assertRaisesRegex(ValueError, 'explicit test rebuild runner'):
            themes.apply(self.plan(boot_theme='adws'), self.backup)

    def test_symlink_theme_and_config_paths_block(self):
        self.login()
        self.write('/usr/share/sddm/themes/adws/link.qml', '').unlink()
        (self.root / 'usr/share/sddm/themes/adws/link.qml').symlink_to('/etc/passwd')
        self.assertTrue(self.plan(login_theme='adws')['conflicts'])
        for value in ('../escape', '/etc/passwd', 'a;command'):
            self.assertTrue(self.plan(login_theme=value)['conflicts'])
        backup_alias = self.base / 'alias'
        backup_alias.symlink_to(self.base)
        (self.root / 'usr/share/sddm/themes/adws/link.qml').unlink()
        with self.assertRaises(ValueError):
            themes.apply(self.plan(login_theme='adws'), backup_alias / 'backup', runner=self.runner)

    def test_backup_collision_never_reuses_directory(self):
        self.login()
        self.backup.mkdir()
        (self.backup / 'precious').write_text('keep')
        with self.assertRaises(FileExistsError):
            themes.apply(self.plan(login_theme='adws'), self.backup, runner=self.runner)
        self.assertEqual((self.backup / 'precious').read_text(), 'keep')
        self.assertFalse((self.root / 'etc/sddm.conf.d/99-adws-theme.conf').exists())

    def test_uki_pe_and_static_splash_block_classic_rebuild(self):
        self.plymouth()
        header = bytearray(64)
        header[:2] = b'MZ'
        struct.pack_into('<I', header, 60, 64)
        coff = bytearray(24)
        coff[:4] = b'PE\0\0'
        struct.pack_into('<H', coff, 6, 3)
        sections = b''.join(name.ljust(40, b'\0') for name in (b'.linux', b'.initrd', b'.splash'))
        self.write('/efi/EFI/Linux/linux.efi', bytes(header) + bytes(coff) + sections)
        proposal = self.plan(boot_theme='adws')
        self.assertEqual(proposal['detected']['uki']['static_splash'], ['/efi/EFI/Linux/linux.efi'])
        self.assertTrue(proposal['unsupported'])
        self.assertFalse(proposal['commands'])

    def test_signing_configuration_and_multiple_generators_block(self):
        self.plymouth()
        self.write('/etc/kernel/uki.conf', '[UKI]\nSecureBootPrivateKey=/etc/kernel/key.pem\n')
        self.write('/usr/bin/dracut', b'fake')
        proposal = self.plan(boot_theme='adws')
        self.assertIn('UKI', ' '.join(proposal['conflicts']))
        self.assertIn('unambiguous', ' '.join(proposal['conflicts']))
        self.assertFalse(proposal['commands'])

    def test_literal_parser_rejects_shell_side_effects(self):
        self.plymouth()
        preset = self.root / 'etc/mkinitcpio.d/linux.preset'
        original = preset.read_text()
        for extra in ('DUMMY=ok;evil\n', 'DUMMY=$(evil)\n', 'DUMMY=`evil`\n',
                      'IFS=/\n', 'default_options="-g /etc/passwd"\n', 'source /tmp/untrusted\n'):
            preset.write_text(original + extra)
            with self.subTest(extra=extra):
                proposal = self.plan(boot_theme='adws')
                self.assertTrue(proposal['conflicts'])
                self.assertFalse(proposal['commands'])
        self.runner.assert_not_called()

    def test_missing_hook_or_splash_is_not_reported_as_supported(self):
        self.plymouth()
        self.write('/etc/mkinitcpio.conf', 'HOOKS=(base filesystems)\n')
        self.write('/etc/kernel/cmdline', 'quiet root=UUID=example\n')
        conflicts = ' '.join(self.plan(boot_theme='adws')['conflicts'])
        self.assertIn('hook', conflicts)
        self.assertIn('splash boot parameter', conflicts)

    def test_same_theme_is_idempotent_and_no_rebuild_needed(self):
        self.plymouth()
        path = self.root / 'etc/plymouth/plymouthd.conf'
        path.write_text(path.read_text().replace('Theme=old', 'Theme=adws'))
        proposal = self.plan(boot_theme='adws')
        self.assertEqual(proposal['status'], 'preserved')
        self.assertEqual(proposal['commands'], [])
        themes.apply(proposal, self.backup, runner=self.runner)
        self.runner.assert_not_called()
        self.assertFalse(self.backup.exists())

    def test_package_transaction_blocks_before_changes(self):
        self.plymouth()
        proposal = self.plan(boot_theme='adws')
        self.write('/var/lib/pacman/db.lck', '')
        with self.assertRaisesRegex(RuntimeError, 'Package transaction'):
            themes.apply(proposal, self.backup, runner=self.runner)
        self.assertFalse(self.backup.exists())

    def test_interrupted_unknown_image_is_not_blindly_restored(self):
        self.plymouth()
        themes.apply(self.plan(boot_theme='adws'), self.backup, runner=self.rebuild)
        journal_path = self.backup / 'journal.json'
        journal = json.loads(journal_path.read_text())
        for entry in journal['entries']:
            if entry['kind'] == 'artifact':
                entry['after'] = None
        journal_path.write_text(json.dumps(journal))
        result = themes.rollback(self.backup)
        self.assertEqual(len(result['conflicts']), 2)
        self.assertEqual((self.root / 'boot/initramfs-linux.img').read_bytes(), b'new initrd')

    def test_ini_without_final_newline_remains_valid(self):
        updated = themes._set_ini('[Daemon]\nShowDelay=5', 'Daemon', 'Theme', 'adws')
        self.assertEqual(themes._ini(updated).get('Daemon', 'ShowDelay'), '5')
        self.assertEqual(themes._ini(updated).get('Daemon', 'Theme'), 'adws')


class BootThemeProcessTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.folder=Path(temporary.name)

    def test_timeout_reaps_detached_term_ignoring_writer(self):
        marker=self.folder/'writer'
        writer="import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=pathlib.Path(%r); exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(.02)')" % str(marker)
        leader='import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",'+repr(writer)+'],start_new_session=True); time.sleep(100)'
        with self.assertRaises(subprocess.TimeoutExpired):
            themes._run_rebuild([sys.executable,'-c',leader],timeout=.3)
        self.assertTrue(marker.exists());last=marker.read_bytes();time.sleep(.15)
        self.assertEqual(marker.read_bytes(),last)

    def test_cancellation_between_fork_and_popen_return_still_reaps_child(self):
        spawned=[];real_popen=themes.subprocess.Popen
        def interrupted(*args,**kwargs):
            child=real_popen(*args,**kwargs);spawned.append(child)
            os.kill(os.getpid(),signal.SIGTERM)
            return child
        with patch.object(themes.subprocess,'Popen',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt),themes._cancellation_signals():
                themes._run_rebuild([sys.executable,'-c','import time;time.sleep(100)'])
        self.assertIsNotNone(spawned[0].poll())

    def parent_cancellation(self,at_spawn=False):
        source=self.folder/'source';(source/'tools').mkdir(parents=True)
        state=self.folder/'state';state.mkdir()
        helper=source/'tools/adws_install_boot_themes.py'
        helper.write_text('''import json,pathlib,signal,sys,time
folder=pathlib.Path(__file__).parents[2]
if '--rollback' in sys.argv:
    (folder/'recovery-requested').touch()
    print(json.dumps({'status':'rolled-back','conflicts':[]}));raise SystemExit(0)
operation=json.loads((folder/'state/system-theme-operation.json').read_text())
assert operation['backup_id']==sys.argv[sys.argv.index('--backup-id')+1]
print(json.dumps({'status':'authorized','backup':operation['backup']}),flush=True)
def cancel(signum,frame):
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    time.sleep(.25)
    (folder/'helper-restored').touch()
    print(json.dumps({'status':'cancelled','backup':operation['backup']}),flush=True)
    raise SystemExit(130)
signal.signal(signal.SIGTERM,cancel)
(folder/'helper-ready').touch()
while True:time.sleep(.05)
''')
        worker=self.folder/'parent.py'
        worker.write_text('''import os,pathlib,signal,sys,time
sys.path.insert(0,sys.argv[1])
import adws_install_boot_themes as themes
# This fixture executes a harmless helper as the current user, never sudo.
themes.os.geteuid=lambda:0
if sys.argv[4]=='at-spawn':
    real_popen=themes.subprocess.Popen
    once=[False]
    def interrupted(*args,**kwargs):
        child=real_popen(*args,**kwargs)
        if not once[0]:
            once[0]=True
            ready=pathlib.Path(sys.argv[3]).parent/'helper-ready'
            deadline=time.monotonic()+5
            while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.01)
            os.kill(os.getpid(),signal.SIGTERM)
        return child
    themes.subprocess.Popen=interrupted
try:
    with themes._cancellation_signals():themes.invoke({'source_root':sys.argv[2],'theme_plan':{}},pathlib.Path(sys.argv[3]))
except KeyboardInterrupt:raise SystemExit(130)
''')
        process=subprocess.Popen([sys.executable,str(worker),str(Path(themes.__file__).parent),str(source),str(state),'at-spawn' if at_spawn else 'later'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.addCleanup(lambda:process.kill() if process.poll() is None else None)
        deadline=time.monotonic()+5
        while not (self.folder/'helper-ready').exists() and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue((self.folder/'helper-ready').exists())
        backup=json.loads((state/'system-theme-operation.json').read_text())['backup']
        self.assertTrue(backup.startswith(str(themes.BACKUP_ROOT)+'/'))
        if not at_spawn:self.assertEqual(themes.operation_backup(state),backup)
        if not at_spawn:process.send_signal(signal.SIGTERM)
        _,stderr=process.communicate(timeout=10)
        self.assertEqual(process.returncode,130,stderr.decode())
        self.assertTrue((self.folder/'helper-restored').exists())
        self.assertTrue((self.folder/'recovery-requested').exists())
        operation=json.loads((state/'system-theme-operation.json').read_text())
        self.assertEqual(operation['state'],'rolled-back')
        self.assertEqual(operation['recovery']['exit'],0)
        self.assertEqual(operation['backup'],backup)
        self.assertIsNone(themes.operation_backup(state))

    def test_parent_cancellation_waits_for_helper_and_retains_recovery_address(self):
        self.parent_cancellation()

    def test_parent_fork_return_cancellation_waits_for_recorded_helper(self):
        self.parent_cancellation(at_spawn=True)

    def test_authorization_cancelled_does_not_request_privilege_again(self):
        source=self.folder/'source';(source/'tools').mkdir(parents=True)
        # Simulate sudo refusing before the root helper can emit its marker.
        helper=source/'tools/adws_install_boot_themes.py';helper.write_text('raise SystemExit(1)\n')
        state=self.folder/'state'
        with patch.object(themes.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(RuntimeError,'not-started'):
                themes.invoke({'source_root':str(source),'theme_plan':{}},state)
        self.assertIsNone(themes.operation_backup(state))
        self.assertFalse((state/'system-theme-recovery-helper.log').exists())

    def test_copy_rechecks_concurrent_target_change_before_replace(self):
        source=self.folder/'source';target=self.folder/'target'
        source.write_bytes(b'our built image');target.write_bytes(b'original')
        before=themes._state(target);copyfileobj=themes.shutil.copyfileobj
        def concurrent(*args,**kwargs):
            copyfileobj(*args,**kwargs);target.write_bytes(b'administrator changed while copying')
        with patch.object(themes.shutil,'copyfileobj',side_effect=concurrent):
            with self.assertRaisesRegex(RuntimeError,'Target changed'):
                themes._copy_atomic(source,target,0o644,before)
        self.assertEqual(target.read_bytes(),b'administrator changed while copying')

    def test_pidfd_signal_rejects_reused_pid_identity(self):
        with patch.object(themes.os,'pidfd_open',return_value=55),patch.object(themes.os,'close'),patch.object(themes,'_process_table',return_value={123:{'start':'new'}}),patch.object(themes.signal,'pidfd_send_signal') as send:
            themes._signal_process(123,'old',signal.SIGTERM)
            send.assert_not_called()

    def test_long_output_keeps_authorization_marker_and_stderr_interactive(self):
        source=self.folder/'source';(source/'tools').mkdir(parents=True)
        helper=source/'tools/adws_install_boot_themes.py'
        helper.write_text('''import json,pathlib,sys
folder=pathlib.Path(__file__).parents[2]
if '--rollback' in sys.argv:
    (folder/'recovery').touch();print(json.dumps({'status':'rolled-back','conflicts':[]}));raise SystemExit(0)
operation=json.loads((folder/'state/system-theme-operation.json').read_text())
print(json.dumps({'status':'authorized','backup':operation['backup']}),flush=True)
print('x'*131072,flush=True)
raise SystemExit(7)
''')
        popen=themes.subprocess.Popen
        with patch.object(themes.os,'geteuid',return_value=0),patch.object(themes.subprocess,'Popen',wraps=popen) as calls:
            with self.assertRaisesRegex(RuntimeError,'recovery attempted'):
                themes.invoke({'source_root':str(source),'theme_plan':{}},self.folder/'state')
        self.assertTrue((self.folder/'recovery').exists())
        for call in calls.call_args_list:self.assertNotIn('stderr',call.kwargs)

    def test_live_recovery_cannot_start_another_rollback(self):
        identifier='a'*32
        (self.folder/'system-theme-operation.json').write_text(json.dumps({'backup_id':identifier,'state':'recovery-still-running'}))
        with self.assertRaisesRegex(RuntimeError,'still running'):themes.operation_backup(self.folder)


if __name__ == '__main__':
    unittest.main()

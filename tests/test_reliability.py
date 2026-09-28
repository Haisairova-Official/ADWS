import hashlib
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_atomic as atomic
import adws_migrate as migration
import adws_setup as setup
import adws_templates as templates
import adws_install_transaction as transaction


class ReliabilityTests(unittest.TestCase):
    def test_interrupt_after_replace_still_restores_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.json';path.write_bytes(b'old')
            replace=os.replace;interrupted=False
            def interrupt_after_replace(source,target):
                nonlocal interrupted
                replace(source,target)
                if not interrupted:
                    interrupted=True;raise KeyboardInterrupt()
            with patch.object(atomic.os,'replace',side_effect=interrupt_after_replace),self.assertRaises(KeyboardInterrupt):
                atomic.replace_files({path:b'new'})
            self.assertEqual(path.read_bytes(),b'old')

    def test_config_pair_failure_restores_bytes_modes_and_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);a = root/'actual';a.write_bytes(b'old config');a.chmod(0o640)
            link = root/'config.jsonc';link.symlink_to(a)
            b = root/'style.css';b.write_bytes(b'old css')
            replace = os.replace
            def fail_css(source, target):
                if target == b: raise OSError('disk full')
                replace(source, target)
            with patch.object(atomic.os, 'replace', side_effect=fail_css), self.assertRaises(OSError):
                atomic.replace_files({link: b'new config', b: b'new css'})
            self.assertTrue(link.is_symlink())
            self.assertEqual(a.read_bytes(), b'old config')
            self.assertEqual(b.read_bytes(), b'old css')
            self.assertEqual(a.stat().st_mode & 0o777, 0o640)
            self.assertFalse(list(root.glob('.adws-write-*')))

    def test_migration_leaves_names_urls_arguments_and_history_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'config.json'
            original = {'image':'/pictures/MNWS-logo.png', 'description':'MNWS',
                        'url':'https://example.org/MNWS-guide', 'command':'echo mnws',
                        'module':'cffi/mnws-test', 'on-click':'mnws -s'}
            p.write_text(json.dumps(original));migration.rewrite(p, [])
            result = json.loads(p.read_text())
            for key in ('image','description','url','command'):self.assertEqual(result[key],original[key])
            self.assertEqual(result['module'],'cffi/adws-test')
            self.assertEqual(result['on-click'],'adws -s')

    def test_migration_follows_symlink_with_spaces_and_preserves_target_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);target=root/'dotfile';link=root/'config.kdl'
            target.write_text('spawn-at-startup "/old install/mnws" "-s"\n');link.symlink_to(target)
            migration.rewrite(link, [], [('/old install','/new install')])
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(),'spawn-at-startup "/new install/adws" "-s"\n')
            self.assertTrue((root/'dotfile.adws-migration.bak').is_file())

    def test_templates_keep_new_defaults_and_known_user_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'old';new=Path(temp)/'new'
            for directory in (root,new):(directory/'config').mkdir(parents=True)
            for name in ('untouched','edited','unknown','adws-windows.kdl'):
                (root/'config'/name).write_text('old');(new/'config'/name).write_text('new')
            baseline=templates.hashes(root);baseline.pop('unknown')
            (root/'config/edited').write_text('my edit')
            (root/'config/adws-windows.kdl').write_text('old rules edit')
            (root/'config/custom').write_text('user added')
            templates.preserve(root,new,baseline)
            self.assertEqual((new/'config/edited').read_text(),'my edit')
            self.assertEqual((new/'config/custom').read_text(),'user added')
            for name in ('untouched','unknown','adws-windows.kdl'):
                self.assertEqual((new/'config'/name).read_text(),'new')

    def test_update_does_not_resurrect_removed_default_templates(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'old';new=Path(temp)/'new'
            (root/'config').mkdir(parents=True);(new/'config').mkdir(parents=True)
            for name in ('obsolete','edited'):(root/'config'/name).write_text('old')
            baseline=templates.hashes(root)
            (root/'config/edited').write_text('user edit')
            templates.preserve(root,new,baseline)
            self.assertFalse((new/'config/obsolete').exists())
            self.assertEqual((new/'config/edited').read_text(),'user edit')

    def test_install_child_keeps_interactive_controlling_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            result=Path(temp)/'result'
            child_code = """
import os
fd = os.open('/dev/tty', os.O_RDWR)
assert os.tcgetpgrp(fd) == os.getpgrp()
os.write(fd, b'PROMPT\\n')
assert os.read(fd, 100).strip() == b'answer'
os.close(fd)
"""
            harness = """
import os, signal, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from adws_install_transaction import run
def cancel(*args): raise KeyboardInterrupt()
signal.signal(signal.SIGTERM, cancel)
fd = os.open(sys.argv[1], os.O_RDWR)
for target in (0, 1, 2): os.dup2(fd, target)
run([sys.executable, '-c', sys.argv[4]])
assert os.tcgetpgrp(fd) == os.getpgrp()
try:
    run([sys.executable, '-c', 'raise SystemExit(7)'])
except subprocess.CalledProcessError as error:
    assert error.returncode == 7
else:
    raise AssertionError('failed child was not reported')
assert os.tcgetpgrp(fd) == os.getpgrp()
Path(sys.argv[3]).write_text('restored')
"""
            master, slave=pty.openpty()
            child=subprocess.Popen([sys.executable,'-c',harness,os.ttyname(slave),str(Path(transaction.__file__).parent),str(result),child_code],start_new_session=True)
            output=b''
            try:
                deadline=time.monotonic()+10
                while b'PROMPT' not in output and time.monotonic()<deadline:
                    if select.select([master],[],[],.1)[0]: output+=os.read(master,65536)
                    if child.poll() is not None: break
                self.assertIn(b'PROMPT',output)
                os.write(master,b'answer\n')
                self.assertEqual(child.wait(timeout=10),0,output)
                self.assertEqual(result.read_text(),'restored')
            finally:
                if child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: child.kill();child.wait()
                os.close(master);os.close(slave)

    def test_failed_install_kills_helpers_even_after_leader_exits(self):
        with tempfile.TemporaryDirectory() as temp:
            ready=Path(temp)/'helper'
            helper_code="""
import os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(60)
"""
            leader_code="""
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]])
deadline = time.monotonic() + 5
while not Path(sys.argv[1]).exists():
    if time.monotonic() > deadline: raise RuntimeError('helper startup timeout')
    time.sleep(.01)
sys.exit(1)
"""
            pid=None
            try:
                with self.assertRaises(subprocess.CalledProcessError):
                    transaction.run([sys.executable,'-c',leader_code,str(ready),helper_code])
                pid=int(ready.read_text())
                def alive():
                    try:return (Path('/proc')/str(pid)/'stat').read_text().split(') ',1)[1][0]!='Z'
                    except FileNotFoundError:return False
                deadline=time.monotonic()+3
                while alive() and time.monotonic()<deadline:time.sleep(.01)
                self.assertFalse(alive(),'build helper survived failed installer')
            finally:
                if pid is not None:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass

    def test_install_snapshot_restores_moves_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'mnws';old.mkdir();(old/'layout').write_text('old')
            new=root/'adws';actual=root/'actual';actual.write_text('original');link=root/'linked';link.symlink_to(actual)
            backup=root/'backup';backup.mkdir()
            snapshot=transaction.Snapshot(backup,[old,new,link])
            old.rename(new);(new/'layout').write_text('changed');actual.write_text('changed');link.unlink();link.write_text('replaced')
            snapshot.restore()
            self.assertEqual((old/'layout').read_text(),'old');self.assertFalse(new.exists())
            self.assertTrue(link.is_symlink());self.assertEqual(actual.read_text(),'original')

    def test_install_cancellation_rolls_back_before_restart(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_STATE_HOME':temp}):
            root=Path(temp);config=root/'config';config.write_text('old')
            def fail(*args):config.write_text('partial install');raise KeyboardInterrupt()
            with patch('adws_runtime.pids',return_value=[]), patch.object(transaction,'integration_paths',return_value=[config]), patch.object(transaction,'run',side_effect=fail):
                with self.assertRaises(KeyboardInterrupt):transaction.install(root)
            self.assertEqual(config.read_text(),'old')

    def test_source_install_rebuilds_even_when_libraries_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lib=root/'.local/lib/waybar';lib.mkdir(parents=True)
            names=('libniri_taskbar.so','libadws_panel.so','libwaybar-space.so')
            for name in names:(lib/name).write_text('OLD')
            (root/'src/panel-rows').mkdir(parents=True)
            (root/'src/panel-rows/libadws_panel.so').write_text('NEW')
            def build(args, **kwargs):
                if args[0]=='bash':(lib/names[0]).write_text('NEW')
                if args[0]=='cc':Path(args[args.index('-o')+1]).write_text('NEW')
                return subprocess.CompletedProcess(args,0)
            with patch.object(Path,'home',return_value=root),patch.object(setup,'ROOT',root),patch.object(setup,'dependency_errors',return_value=[]),patch('adws_prebuilt.install',return_value=False),patch.object(setup,'confirm',return_value=True),patch.object(setup,'check',return_value=0),patch.object(setup.shutil,'which',return_value='/usr/bin/tool'),patch.object(setup.subprocess,'run',side_effect=build),patch.object(setup.subprocess,'check_output',return_value=''):
                setup.prepare()
            for name in names:self.assertEqual((lib/name).read_text(),'NEW')

    def test_failed_restart_restores_files_before_old_process(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_STATE_HOME':temp}):
            root=Path(temp);config=root/'config';config.write_text('old')
            active={'desktop':True};events=[]
            def ids(component):return [os.getpid()] if active.get(component) else []
            def stop(args, **kwargs):active[args[0]]=False;events.append('stop');return 0
            def install_or_start(command, env=None):
                if command[0]=='bash':config.write_text('new');events.append('install')
                else:raise RuntimeError('new component failed')
            real_spawn=subprocess.Popen
            def spawn(command, *args, **kwargs):
                if command[0]=='cp':return real_spawn(command,*args,**kwargs)
                self.assertEqual(config.read_text(),'old')
                events.append('restore old process')
                return None
            with patch('adws_runtime.pids',side_effect=ids),patch('adws_runtime.main',side_effect=stop),patch.object(transaction,'integration_paths',return_value=[config]),patch.object(transaction,'run',side_effect=install_or_start),patch.object(transaction.subprocess,'Popen',side_effect=spawn):
                with self.assertRaisesRegex(RuntimeError,'new component failed'):transaction.install(root)
            self.assertEqual(events,['stop','install','restore old process'])

    def test_installer_and_updater_share_one_lock(self):
        import adws_upgrade
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_STATE_HOME':temp}):
            with adws_upgrade.update_lock(), patch('adws_runtime.pids') as ids:
                with self.assertRaises(BlockingIOError):transaction.install(Path(temp))
                ids.assert_not_called()

    def test_stop_failure_does_not_duplicate_running_component(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_STATE_HOME':temp}):
            with patch('adws_runtime.pids',side_effect=lambda name:[os.getpid()] if name=='desktop' else []),patch('adws_runtime.main',return_value=1),patch.object(transaction,'Snapshot') as snapshot,patch.object(transaction.subprocess,'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError,'Could not stop desktop'):transaction.install(Path(temp))
                snapshot.assert_not_called();spawn.assert_not_called()

    def test_old_python_is_rejected_before_stopping_components(self):
        with patch.object(transaction.sys,'version_info',(3,10)),patch('adws_runtime.pids') as ids:
            with self.assertRaisesRegex(RuntimeError,'3.11'):transaction.install()
            ids.assert_not_called()

    def test_failed_stop_before_rollback_leaves_backup_for_recovery(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_STATE_HOME':temp}):
            root=Path(temp);config=root/'config';config.write_text('old');active={'desktop':True}
            def ids(name):return [os.getpid()] if active.get(name) else []
            stops=0
            def stop(*args,**kwargs):
                nonlocal stops
                stops+=1
                if stops==1:active['desktop']=False;return 0
                return 1
            def fail(*args,**kwargs):
                config.write_text('new');active['desktop']=True;raise RuntimeError('failure after partial start')
            with patch('adws_runtime.pids',side_effect=ids),patch('adws_runtime.main',side_effect=stop),patch.object(transaction,'integration_paths',return_value=[config]),patch.object(transaction,'run',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'Could not stop desktop before restoring files'):transaction.install(root)
            self.assertEqual(config.read_text(),'new')
            manifests=list((root/'adws-install-backups').glob('install-*/manifest.json'))
            self.assertEqual(len(manifests),1)
            saved=json.loads(manifests[0].read_text())[0]['backup']
            self.assertEqual(Path(saved).read_text(),'old')

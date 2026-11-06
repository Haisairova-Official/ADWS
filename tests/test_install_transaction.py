from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_transaction as transaction


class InstallerStateRollbackTests(unittest.TestCase):
    def test_one_component_restore_error_does_not_skip_other_components_or_topbar(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);root=home/'source';root.mkdir()
            process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
            try:
                active={'desktop':True,'taskbar':True}
                def pids(component):return [process.pid] if active.get(component) else []
                def control(argv,**kwargs):active[argv[0]]=False;return 0
                bars=Mock()
                def operation(backup):raise ValueError('configuration failed')
                environment={'HOME':str(home),'XDG_STATE_HOME':str(home/'state')}
                with patch.dict(os.environ,environment),patch('adws_runtime.pids',side_effect=pids),patch('adws_runtime.main',side_effect=control),patch.object(transaction,'integration_paths',return_value=[]),patch('adws_install_bar_lifecycle.TopbarLifecycle',return_value=bars),patch.object(transaction.subprocess,'Popen',side_effect=[OSError('desktop start failed'),Mock()]) as restart:
                    with self.assertRaisesRegex(RuntimeError,'desktop start failed') as caught:
                        transaction.install(root,operation=operation,restart_profiles=[{'config':str(home/'top.jsonc'),'style':str(home/'top.css')}])
                self.assertIsInstance(caught.exception.__cause__,ValueError)
                self.assertEqual(restart.call_count,2)
                bars.stop_new.assert_called_once()
                bars.restore_old.assert_called_once()
                bars.close.assert_called_once()
            finally:
                process.terminate();process.wait(timeout=5)

    def test_restart_from_headless_installer_uses_captured_desktop_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);root=home/'new source';root.mkdir()
            original={'PATH':os.environ.get('PATH','/usr/bin'),'HOME':str(home),
                      'LANG':'C.UTF-8','WAYLAND_DISPLAY':'wayland-original',
                      'DISPLAY':':77','NIRI_SOCKET':str(home/'original-niri.sock'),
                      'XDG_RUNTIME_DIR':str(home/'runtime'),
                      'ADWS_INSTALL_MANAGED':'1','ADWS_INSTALL_PLAN':'/old-reviewed-plan',
                      'ADWS_NIRI_METHOD':'source','ADWS_BUILD_MIRROR':'1'}
            process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],env=original)
            try:
                active={'desktop':True};calls=[]
                def pids(component):return [process.pid] if active.get(component,False) else []
                def control(argv,**kwargs):
                    self.assertEqual(argv,['desktop','--stop']);active['desktop']=False;return 0
                def launch(argv,env=None,**kwargs):
                    calls.append((argv,dict(env)));active['desktop']=True
                installer={'HOME':str(home),'XDG_STATE_HOME':str(home/'state'),
                           'PATH':original['PATH'],'LANG':'C.UTF-8',
                           'ADWS_INSTALL_MANAGED':'1','ADWS_INSTALL_PLAN':'/new-reviewed-plan'}
                with patch.dict(os.environ,installer,clear=True),patch('adws_runtime.pids',side_effect=pids),patch('adws_runtime.main',side_effect=control),patch.object(transaction,'integration_paths',return_value=[]),patch.object(transaction,'run',side_effect=launch):
                    self.assertEqual(transaction.install(root,operation=lambda backup:None),0)
                self.assertEqual(len(calls),1)
                argv,environment=calls[0]
                self.assertEqual(argv,[str(root/'adws'),'desktop','--start'])
                self.assertEqual(environment,{k:v for k,v in original.items() if not k.startswith('ADWS_')})
                manifests=list((home/'state/adws-install-backups').rglob('manifest.json'))
                self.assertEqual(len(manifests),1)
                self.assertNotIn('wayland-original',manifests[0].read_text())
            finally:
                process.terminate();process.wait(timeout=5)

    def test_rollback_keeps_journal_log_bootstrap_and_unknown_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);state=home/'state';config=home/'config';data=home/'data';cache=home/'cache'
            root=home/'source';root.mkdir()
            environment={'HOME':str(home),'XDG_STATE_HOME':str(state),'XDG_CONFIG_HOME':str(config),
                         'XDG_DATA_HOME':str(data),'XDG_CACHE_HOME':str(cache),'NIRI_CONFIG':str(config/'niri/config.kdl')}
            durable=[state/'adws/installer/run/install.log',state/'adws/installer/run/progress.json',
                     state/'adws/bootstrap/hash-source/install.sh',state/'adws/my-notes.txt']
            for path in durable:path.parent.mkdir(parents=True,exist_ok=True);path.write_text('before\n')
            inventory=state/'adws/install-record.json';inventory.write_text('old inventory')
            with patch.dict(os.environ,environment),patch.object(Path,'home',return_value=home):
                paths=transaction.integration_paths(root)
            # Restrict the fixture to this temporary home; production system
            # command links are neither read nor modified by this regression.
            paths=[path for path in paths if path.is_relative_to(home)]
            self.assertNotIn(state/'adws',paths)
            backup=home/'backup';backup.mkdir()
            snapshot=transaction.Snapshot(backup,paths)
            config_file=config/'adws/new-setting.json';config_file.parent.mkdir(parents=True);config_file.write_text('new config')
            inventory.write_text('new inventory')
            for path in durable:path.write_text('after; retain failure evidence\n')
            unknown=state/'adws/new-user-state';unknown.write_text('preserve this too')
            # The tee process keeps an open log descriptor during rollback.
            with durable[0].open('a') as stream:
                snapshot.restore()
                stream.write('rollback finished\n')
            self.assertFalse(config_file.exists())
            self.assertEqual(inventory.read_text(),'old inventory')
            self.assertEqual(unknown.read_text(),'preserve this too')
            self.assertTrue(durable[0].read_text().endswith('rollback finished\n'))
            for path in durable:self.assertIn('retain failure evidence',path.read_text())

    def test_fresh_failed_install_removes_new_inventory_but_retains_installer_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);inventory=root/'adws/install-record.json';journal=root/'adws/installer/progress.json'
            journal.parent.mkdir(parents=True);journal.write_text('running')
            backup=root/'backup';backup.mkdir()
            snapshot=transaction.Snapshot(backup,[inventory])
            inventory.write_text('partial inventory');journal.write_text('failed')
            snapshot.restore()
            self.assertFalse(inventory.exists())
            self.assertEqual(journal.read_text(),'failed')


if __name__=='__main__':unittest.main()

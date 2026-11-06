"""Exercise interpreter replacement without replacing the host Python or packages."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_workflow as workflow


class InterpreterHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='adws-python-handoff-');self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.home=self.root/'home';self.home.mkdir()
        self.source=self.root/'source';self.source.mkdir();(self.source/'install.sh').write_text('# fixture\n')
        self.env=patch.dict(os.environ,{'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.home/'.config'),
            'XDG_DATA_HOME':str(self.home/'.local/share'),'XDG_STATE_HOME':str(self.home/'.local/state'),
            'NIRI_CONFIG':'','ADWS_INSTALL_PLAN':'','ADWS_INSTALL_MANAGED':''})
        self.env.start();self.addCleanup(self.env.stop)
        self.directory=workflow.state_root()/'fixture';self.directory.mkdir(parents=True,mode=0o700)
        self.plan={'schema_version':workflow.SCHEMA,'approved':True,'mode':'fresh','home':str(self.home),
            'source_root':str(self.source),'source_fingerprint':workflow.fingerprint(self.source),
            'config_home':str(self.home/'.config'),'data_home':str(self.home/'.local/share'),
            'niri_config':'','blocking':[],'system_upgrade':True,'features':{'manager':'pacman'},
            'package_candidates':['fixture-package'],'niri_method':'repository','mirror':'official'}
        workflow.write_json(self.directory/'plan.json',self.plan)
        self.journal=workflow.Journal(self.directory,self.plan)
        self.journal.data['steps']['packages']={'status':'passed'}
        self.token='fixture-token'
        self.journal.data['interpreter_handoff']={'status':'pending','token_sha256':hashlib.sha256(self.token.encode()).hexdigest(),
            'plan_digest':workflow.Journal.digest(self.plan),'target':workflow.python_identity()}
        self.journal.save()

    def test_handoff_consumed_once_only_after_actual_packages_revalidated(self):
        with patch('adws_niri_install.installed_packages',return_value={'fixture-package'}) as installed:
            workflow.consume_interpreter_handoff(self.plan,self.directory,self.token)
            installed.assert_called_once_with('pacman',['fixture-package'])
            with self.assertRaises(ValueError):workflow.consume_interpreter_handoff(self.plan,self.directory,self.token)
        data=json.loads((self.directory/'progress.json').read_text())
        self.assertEqual(data['interpreter_handoff']['status'],'resumed')
        self.assertNotIn('token_sha256',data['interpreter_handoff'])

    def test_invalid_handoff_cannot_resume_or_install_packages(self):
        original=json.loads((self.directory/'progress.json').read_text())
        cases=[('wrong token',lambda d:None,'bad'),
               ('package step incomplete',lambda d:d['steps']['packages'].update(status='running'),self.token),
               ('another interpreter',lambda d:d['interpreter_handoff']['target'].update(inode=-1),self.token),
               ('changed plan digest',lambda d:d['interpreter_handoff'].update(plan_digest='changed'),self.token)]
        for caption,mutate,token in cases:
            with self.subTest(caption):
                data=json.loads(json.dumps(original));mutate(data);workflow.write_json(self.directory/'progress.json',data)
                with patch('adws_niri_install.installed_packages') as installed, patch('adws_setup.install_packages') as mutate_packages:
                    with self.assertRaises(ValueError):workflow.consume_interpreter_handoff(self.plan,self.directory,token)
                    installed.assert_not_called();mutate_packages.assert_not_called()
        workflow.write_json(self.directory/'progress.json',original)
        with patch('adws_niri_install.installed_packages',return_value=set()),patch('adws_setup.install_packages') as mutate_packages:
            with self.assertRaisesRegex(ValueError,'依赖再次缺失'):workflow.consume_interpreter_handoff(self.plan,self.directory,self.token)
            mutate_packages.assert_not_called()

    def test_internal_entry_validates_source_before_consuming_token(self):
        (self.source/'install.sh').write_text('# changed\n')
        with patch('builtins.input',side_effect=AssertionError('must not ask')),patch.object(workflow,'_execute') as execute:
            with self.assertRaisesRegex(ValueError,'源码已改变'):
                workflow.main(['--continue-after-upgrade',str(self.directory),'--continuation-token',self.token])
            execute.assert_not_called()
        self.assertEqual(json.loads((self.directory/'progress.json').read_text())['interpreter_handoff']['status'],'pending')

    def test_handoff_rejects_external_symlink_and_writable_journal(self):
        with self.assertRaises(ValueError):workflow.continuation_directory(self.source)
        link=workflow.state_root()/'link';link.symlink_to(self.directory,target_is_directory=True)
        with self.assertRaises(ValueError):workflow.continuation_directory(link)
        (self.directory/'progress.json').chmod(0o666)
        with self.assertRaises(ValueError):workflow.continuation_directory(self.directory)

    def test_no_restart_loop_if_interpreter_changes_twice(self):
        with patch.object(workflow,'replacement_python',return_value=(sys.executable,workflow.python_identity())):
            with self.assertRaisesRegex(RuntimeError,'再次改变'):workflow.restart_after_python_upgrade(self.plan,self.journal)

    def test_new_handoff_protects_journal_created_under_cooperative_umask(self):
        self.journal.data.pop('interpreter_handoff');self.journal.save();self.directory.chmod(0o775)
        with patch.object(workflow,'replacement_python',return_value=(sys.executable,workflow.python_identity())):
            with self.assertRaises(workflow.InterpreterRestart):workflow.restart_after_python_upgrade(self.plan,self.journal)
        self.assertEqual(self.directory.stat().st_mode&0o777,0o700)
        self.assertEqual(workflow.continuation_directory(self.directory),self.directory)

    def test_real_reexec_recovers_old_stdlib_loss_and_releases_tee_lock_and_environment(self):
        # Run a disposable interpreter inode. The fake package transaction
        # replaces only that copy, then removes old stdlib search paths.
        interpreter=self.root/'python-fixture';shutil.copy2('/proc/self/exe',interpreter)
        tools=Path(workflow.__file__).resolve().parent
        folder=self.source/'tools';folder.mkdir();driver=folder/'adws_install_workflow.py'
        driver.write_text(DRIVER.replace('__TOOLS__',repr(str(tools))).replace('__ROOT__',repr(str(self.root))))
        env=dict(os.environ,HOME=str(self.home),XDG_STATE_HOME=str(self.home/'.local/state'),
                 XDG_CONFIG_HOME=str(self.home/'.config'),XDG_DATA_HOME=str(self.home/'.local/share'))
        for key in ('ADWS_INSTALL_PLAN','ADWS_INSTALL_MANAGED','ADWS_NIRI_METHOD','ADWS_BUILD_MIRROR','PYTHONPATH','PYTHONHOME'):
            env.pop(key,None)
        result=subprocess.run([str(interpreter),str(driver)],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        report=json.loads((self.root/'actual-result.json').read_text())
        self.assertTrue(report['old_stdlib_missing']);self.assertTrue(report['new_stdlib_usable'])
        self.assertTrue(report['stdout_restored']);self.assertTrue(report['lock_released']);self.assertTrue(report['environment_restored'])
        self.assertEqual(report['package_runs'],1);self.assertEqual(report['handoff_status'],'resumed')
        self.assertNotIn('确认',result.stdout)
        progress=json.loads((workflow.state_root()/'actual/progress.json').read_text())
        self.assertEqual(progress['steps']['packages']['status'],'passed')
        self.assertFalse((workflow.state_root()/'actual/failure.json').exists())


DRIVER=r'''
import builtins,fcntl,json,os,shutil,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,__TOOLS__)
import adws_install_workflow as w
import adws_setup as setup
import adws_niri_install as niri
import adws_install_arch_packages as arch
root=Path(__ROOT__);marker=root/'packages-installed.json';directory=w.state_root()/'actual'
builtins.input=lambda *args: (_ for _ in ()).throw(AssertionError('unexpected user prompt'))
niri.installed_packages=lambda manager,wanted:set(wanted) if marker.exists() else set()
arch.verify_sources=lambda proposal:True
if '--continue-after-upgrade' in sys.argv:
    # These run before execute reacquires its lock or starts its next log tee.
    report=json.loads(marker.read_text())
    with (w.state_root()/'execution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);report['lock_released']=True
    report['stdout_restored']=os.readlink('/proc/self/fd/1')==os.environ['FIXTURE_ORIGINAL_STDOUT']
    report['environment_restored']=all(key not in os.environ for key in ('ADWS_INSTALL_PLAN','ADWS_INSTALL_MANAGED','ADWS_NIRI_METHOD','ADWS_BUILD_MIRROR'))
    def finish(plan,directory):
        journal=w.Journal(directory,plan)
        journal.step('packages',lambda:(_ for _ in ()).throw(AssertionError('repeated system upgrade')),
                     lambda:set(plan['package_candidates'])<=niri.installed_packages('pacman',plan['package_candidates']))
        import zipfile
        report['new_stdlib_usable']=hasattr(zipfile,'ZipFile')
        report['handoff_status']=journal.data['interpreter_handoff']['status']
        (root/'actual-result.json').write_text(json.dumps(report))
        return 0
    w._execute=finish
    raise SystemExit(w.main(sys.argv[1:]))
os.environ['FIXTURE_ORIGINAL_STDOUT']=os.readlink('/proc/self/fd/1')
plan={'schema_version':w.SCHEMA,'approved':True,'mode':'fresh','home':str(Path.home()),
      'source_root':str(root/'source'),'source_fingerprint':w.fingerprint(root/'source'),
      'config_home':os.environ['XDG_CONFIG_HOME'],'data_home':os.environ['XDG_DATA_HOME'],
      'niri_config':'','blocking':[],'system_upgrade':True,'features':{'manager':'pacman'},
      'package_candidates':['fixture-package'],'package_review':{},'niri_method':'repository','mirror':'official'}
def packages(programs,*,system_upgrade=False):
    assert system_upgrade is True
    replacement=root/'new-python';shutil.copy2('/proc/self/exe',replacement)
    os.replace(replacement,sys.executable)
    assert 'zipfile' not in sys.modules
    sys.path[:]=[__TOOLS__]
    try:import zipfile
    except ModuleNotFoundError:missing=True
    else:missing=False
    marker.write_text(json.dumps({'package_runs':1,'old_stdlib_missing':missing}))
setup.install_packages=packages
raise SystemExit(w.execute(plan,directory))
'''


if __name__=='__main__':unittest.main()

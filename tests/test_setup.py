import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_setup as setup
from adws_i18n import tr as _tr


class SetupTests(unittest.TestCase):
    def test_build_environment_rejects_old_system_and_uses_rustup(self):
        import os, subprocess
        def version(command, **kwargs):
            modern = '/.cargo/bin/' in command[0]
            name = Path(command[0]).name
            return subprocess.CompletedProcess(command, 0, name + (' 1.87.0' if modern else ' 1.75.0'), '')
        def which(name, path=None):
            return ('/home/test/.cargo/bin/' if path.startswith('/home/test/.cargo/bin:') else '/usr/bin/') + name
        with patch.dict(os.environ, {'PATH':'/usr/bin', 'CARGO_HOME':'/home/test/.cargo'}), patch.object(setup.shutil, 'which', side_effect=which), patch.object(setup.subprocess, 'run', side_effect=version):
            self.assertTrue(setup.build_environment()['PATH'].startswith('/home/test/.cargo/bin:'))

    def test_build_environment_reports_missing_supported_toolchain(self):
        import subprocess
        with patch.object(setup.shutil, 'which', return_value='/bin/old'), patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'rustc 1.75.0','')):
            with self.assertRaisesRegex(RuntimeError, '1.87'):
                setup.build_environment()

    def test_decline_does_not_install(self):
        with patch.object(setup.shutil, 'which', return_value='/bin/tool'), patch.object(setup, 'confirm', return_value=False), patch.object(setup.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                setup.install_packages(['waybar'])
            run.assert_not_called()

    def test_install_requested_packages(self):
        with patch.object(setup.shutil, 'which', return_value='/bin/tool'), patch.object(setup, 'confirm', return_value=True), patch.object(setup.os, 'geteuid', return_value=0), patch.object(setup.subprocess, 'run') as run:
            setup.install_packages(['waybar', 'waybar'])
            run.assert_called_once_with(['apt-get', 'install', 'waybar'], check=True)

    def test_unsupported(self):
        with patch.object(setup.shutil, 'which', return_value=None), patch.object(setup.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                setup.install_packages(['waybar'])
            run.assert_not_called()

    def test_recheck_stops_on_failure(self):
        with patch('adws_niri_install.ensure_niri',return_value='/bin/niri'), patch.object(setup, 'ensure_waybar', return_value='/bin/tool'), patch.object(setup, 'dependency_errors', return_value=['missing']), patch('adws_runtime_dependencies.missing_dependencies',return_value={}), patch.object(setup, 'install_packages'), patch.object(setup.shutil, 'which', return_value='/bin/tool'):
            with self.assertRaisesRegex(RuntimeError, _tr('补齐后仍有问题')):
                setup.prepare()

    def test_cancel(self):
        with patch.object(setup, 'prepare', side_effect=KeyboardInterrupt):
            self.assertEqual(setup.main(), 130)

    def test_atomic_library_install(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'source', Path(directory)/'target'
            source.write_bytes(b'new'); target.write_bytes(b'old')
            with target.open('rb') as old:
                setup.atomic_install(source, target)
                self.assertEqual(old.read(), b'old')
            self.assertEqual(target.read_bytes(), b'new')


class ManagedSetupTests(unittest.TestCase):
    def plan(self, **values):
        return {'features': {'manager': 'pacman'}, 'package_candidates': ['waybar', 'fontconfig'],
                'build_fallback': False, 'niri_method': 'repository', **values}

    def test_known_choices_reuse_plan_without_prompt(self):
        with patch.object(setup, 'approved_plan', return_value=self.plan()), patch.object(setup, 'ask') as ask:
            self.assertTrue(setup.confirm(_tr('是否快速安装预构建组件？无需 Rust/Cargo 或 C 编译器。')))
            self.assertFalse(setup.confirm(_tr('是否现在构建并安装这些组件？首次构建可能需要下载依赖。')))
            with self.assertRaisesRegex(RuntimeError, 'NEW_PLAN_REQUIRED'):
                setup.confirm('Unreviewed decision')
            ask.assert_not_called()

    @patch('adws_niri_install.installed_packages', return_value=set())
    def test_exact_approved_packages_only(self, installed):
        with patch.object(setup, 'approved_plan', return_value=self.plan()), patch.object(setup.shutil,'which',return_value='/bin/tool'), patch.object(setup.os,'geteuid',return_value=0), patch.object(setup.subprocess,'run') as run:
            setup.install_packages(['waybar'])
            run.assert_called_once_with(['pacman','-S','--needed','waybar'],check=True)
            run.reset_mock()
            with self.assertRaisesRegex(RuntimeError, 'NEW_PLAN_REQUIRED.*unapproved'):
                setup.install_packages(['unreviewed-package'])
            run.assert_not_called()

    def test_package_manager_change_needs_new_plan(self):
        with patch.object(setup, 'approved_plan', return_value=self.plan()), patch.object(setup.shutil,'which',return_value=None), patch.object(setup.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'NEW_PLAN_REQUIRED'):
                setup.install_packages(['waybar'])
            run.assert_not_called()

    @patch('adws_niri_install.installed_packages', return_value={'fontconfig'})
    def test_explicit_arch_upgrade_uses_whole_transaction_and_keeps_final_confirmation(self, installed):
        with patch.object(setup,'approved_plan',return_value=self.plan(system_upgrade=True)), patch.object(setup.shutil,'which',return_value='/bin/tool'), patch.object(setup.os,'geteuid',return_value=0), patch.object(setup,'checked_run') as run:
            setup.install_packages(['waybar','fontconfig'],system_upgrade=True)
            run.assert_called_once_with(['pacman','--config','/etc/pacman.conf','-Syu','--needed','--','waybar'],check=True)
            self.assertNotIn('--noconfirm',run.call_args.args[0])

    def test_downstream_dependencies_after_upgrade_never_repeat_package_transaction(self):
        with patch.object(setup,'approved_plan',return_value=self.plan(system_upgrade=True)), patch.object(setup.shutil,'which',return_value='/bin/tool'), patch('adws_niri_install.installed_packages',return_value={'waybar','fontconfig'}) as installed, patch.object(setup,'checked_run') as run:
            setup.install_packages(['waybar'])
            installed.assert_called_once_with('pacman',['waybar'])
            run.assert_not_called()
            installed.return_value=set()
            with self.assertRaisesRegex(RuntimeError,'NEW_PLAN_REQUIRED.*missing.*waybar'):
                setup.install_packages(['waybar'])
            run.assert_not_called()

    def test_full_upgrade_requires_explicit_arch_plan_authorization(self):
        plans=[None,self.plan(),self.plan(system_upgrade=False),self.plan(system_upgrade=True,features={'manager':'apt-get'})]
        for proposal in plans:
            with self.subTest(plan=proposal), patch.object(setup,'approved_plan',return_value=proposal), patch.object(setup.shutil,'which',return_value='/bin/tool'), patch.object(setup,'checked_run') as run, patch.object(setup,'ask') as ask:
                with self.assertRaisesRegex(RuntimeError,'NEW_PLAN_REQUIRED.*not approved'):
                    setup.install_packages(['waybar'],system_upgrade=True)
                run.assert_not_called();ask.assert_not_called()

    def test_niri_source_build_does_not_run_a_second_full_upgrade(self):
        import os
        import adws_niri_install as niri
        packages=niri.BUILD_PACKAGES['pacman']
        class StopBeforeBuild(Exception):pass
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'XDG_CACHE_HOME':directory}), patch.object(setup,'approved_plan',return_value=self.plan(system_upgrade=True,package_candidates=packages)), patch.object(setup.shutil,'which',side_effect=lambda name:None if name=='niri' else '/bin/'+name), patch.object(setup.os,'geteuid',return_value=0), patch('adws_niri_install.installed_packages',return_value=set(packages)), patch.object(setup,'checked_run') as run, patch.object(niri,'checked_run',side_effect=StopBeforeBuild):
            setup.install_packages(packages,system_upgrade=True)
            with self.assertRaises(StopBeforeBuild):
                niri.build_source(lambda _:True,setup.install_packages,'pacman')
            self.assertEqual(run.call_count,1,'Niri source dependency check must not repeat the full upgrade')
            self.assertIn('-Syu',run.call_args.args[0])

    def test_managed_mode_without_approved_plan_fails_closed(self):
        with patch.dict(setup.os.environ, {'ADWS_INSTALL_MANAGED':'1'},clear=True), patch('adws_install_workflow.approved_plan', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'NEW_PLAN_REQUIRED'):
                setup.approved_plan()

    def test_source_consent_is_independent_of_other_builds(self):
        with patch.object(setup, 'approved_plan', return_value=self.plan(build_fallback=True,niri_method='repository')):
            self.assertTrue(setup.confirm(_tr('是否现在构建并安装这些组件？首次构建可能需要下载依赖。')))
            self.assertFalse(setup.confirm(_tr('源码构建需要新版本 Rust。是否通过官方 rustup 安装／更新 stable 工具链？不会移除系统 Rust。')))

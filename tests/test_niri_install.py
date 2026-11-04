import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_niri_install as niri


def completed(stdout='',stderr='',code=0):
    return subprocess.CompletedProcess([],code,stdout,stderr)


class NiriInstallTests(unittest.TestCase):
    def test_repo_candidates_use_only_configured_sources(self):
        with patch.object(niri,'query',return_value=completed('niri:\n  Installed: (none)\n  Candidate: 26.04-1\nmissing:\n  Candidate: (none)\n')) as query:
            self.assertEqual(niri.package_candidates('apt-get',['niri','missing']),{'niri':'26.04-1'})
            self.assertEqual(query.call_args.args[0],['apt-cache','policy','niri','missing'])
        with patch.object(niri,'query',return_value=completed('Name : niri\nVersion : 26.04-2\n','error: package missing was not found',1)):
            self.assertEqual(niri.package_candidates('pacman',['niri','missing']),{'niri':'26.04-2'})
        with patch.object(niri,'query',return_value=completed('niri 26.04\n')):
            self.assertEqual(niri.package_candidates('dnf',['niri']),{'niri':'26.04'})
        for value in ('26.04-1','1:26.04-2','27.01'):self.assertTrue(niri.suitable_package(value))
        for value in ('25.08','0.1.10',None,'bad'):self.assertFalse(niri.suitable_package(value))

    def test_repository_failure_is_not_reported_as_missing_package(self):
        with patch.object(niri,'query',return_value=completed('', 'no database',1)):
            for manager in ('apt-get','pacman','dnf'):
                with self.assertRaises(RuntimeError):niri.package_candidates(manager,['niri'])

    def test_existing_compositor_and_config_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.kdl';path.write_text('// my fork configuration\n')
            with patch.dict(os.environ,{'NIRI_CONFIG':str(path)}),patch.object(niri.shutil,'which',return_value='/custom/niri'),patch.object(niri,'check_binary',return_value='niri fork'),patch.object(niri,'build_source') as build:
                confirm=Mock();install=Mock();self.assertEqual(niri.ensure_niri(confirm,install),'/custom/niri')
                confirm.assert_not_called();install.assert_not_called();build.assert_not_called()
            self.assertEqual(path.read_text(),'// my fork configuration\n')

    def test_decline_does_not_install_or_query_repositories(self):
        with patch.object(niri.shutil,'which',return_value=None),patch.object(niri,'package_candidates') as query:
            install=Mock()
            with self.assertRaises(RuntimeError):niri.ensure_niri(Mock(return_value=False),install)
            install.assert_not_called();query.assert_not_called()

    def test_repository_install_assembles_session_without_starting_it(self):
        with patch.object(niri.shutil,'which',side_effect=[None,'/usr/bin/niri']),patch.object(niri,'package_manager',return_value='apt-get'),patch.object(niri,'package_candidates',return_value={'niri':'26.04-1'}),patch.object(niri,'ask',return_value='1'),patch.object(niri,'check_binary'),patch.object(niri,'session_dependencies',return_value=['foot']) as deps,patch.object(niri,'initial_config') as config,patch.object(niri,'session_report') as report,patch.object(niri,'build_source') as build:
            confirm=Mock(return_value=True);install=Mock();niri.ensure_niri(confirm,install)
            install.assert_called_once_with(programs=['niri']);build.assert_not_called()
            deps.assert_called_once();config.assert_called_once_with('/usr/bin/niri',['foot'],confirm);report.assert_called_once()

    def test_no_repo_package_offers_source_and_empty_answer_cancels(self):
        for choice,expect_build in [('',False),('2',True)]:
            with patch.object(niri.shutil,'which',return_value=None),patch.object(niri,'package_manager',return_value='apt-get'),patch.object(niri,'package_candidates',return_value={}),patch.object(niri,'ask',return_value=choice),patch.object(niri,'build_source',return_value='/usr/local/bin/niri') as build,patch.object(niri,'check_binary'),patch.object(niri,'session_dependencies',return_value=['foot']),patch.object(niri,'initial_config'),patch.object(niri,'session_report'):
                if expect_build:niri.ensure_niri(Mock(return_value=True),Mock());build.assert_called_once()
                else:
                    with self.assertRaises(RuntimeError):niri.ensure_niri(Mock(return_value=True),Mock())
                    build.assert_not_called()

    def test_source_commit_mismatch_stops_before_privilege_or_build(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_CACHE_HOME':folder}),patch.object(niri.shutil,'which',return_value=None),patch.object(niri.subprocess,'run'),patch.object(niri,'query',return_value=completed('wrong\n')),patch.object(niri,'install_source_files') as install:
            with self.assertRaises(RuntimeError):niri.build_source(Mock(return_value=True),Mock(),'apt-get')
            install.assert_not_called()

    def test_source_paths_keep_display_manager_and_use_absolute_exec(self):
        with tempfile.TemporaryDirectory() as folder:
            tree=Path(folder);resources=tree/'resources';resources.mkdir();binary=tree/'niri';binary.write_bytes(b'fixture')
            (tree/'LICENSE').write_text('license')
            for name,text in {'niri-session':'#!/bin/sh\nexec niri --session\n','niri.service':'[Service]\nExecStart=niri --session\n','niri-shutdown.target':'[Unit]\n','niri.desktop':'[Desktop Entry]\nExec=niri-session\n','niri-portals.conf':'[preferred]\ndefault=gnome;gtk;\n'}.items():(resources/name).write_text(text)
            files=niri.source_files(tree,binary)
            self.assertIn(Path('/usr/local/share/wayland-sessions/niri.desktop'),files)
            self.assertIn(b'ExecStart=/usr/local/bin/niri --session',files[Path('/etc/systemd/user/niri.service')][0])
            self.assertIn(b'Exec=/usr/local/bin/niri-session',files[Path('/usr/local/share/wayland-sessions/niri.desktop')][0])
            self.assertFalse(any('gdm' in str(path) or 'sddm' in str(path) or 'lightdm' in str(path) for path in files))

    def test_install_conflict_never_overwrites_and_decline_leaves_no_files(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(niri,'privileged') as root:
            target=Path(folder)/'niri';target.symlink_to(Path(folder)/'missing')
            with self.assertRaises(RuntimeError):niri.install_source_files({target:(b'new',0o755)},Mock(return_value=True))
            root.assert_not_called();self.assertTrue(target.is_symlink());target.unlink()
            with self.assertRaises(RuntimeError):niri.install_source_files({target:(b'new',0o755)},Mock(return_value=False))
            root.assert_not_called();self.assertFalse(target.exists())

    def test_atomic_source_install_rolls_back_only_new_files(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            first,second=Path(folder)/'niri',Path(folder)/'session'
            def root(command):
                if command[0]=='install':shutil.copyfile(command[-2],command[-1])
                elif command[0]=='ln':
                    if command[-1]==str(second):raise OSError('fixture failure')
                    os.link(command[-2],command[-1])
                elif command[0]=='rm':Path(command[-1]).unlink()
                else:self.fail(command)
            with patch.object(niri,'privileged',side_effect=root):
                with self.assertRaises(OSError):niri.install_source_files({first:(b'niri',0o755),second:(b'session',0o755)},Mock(return_value=True))
            self.assertFalse(first.exists());self.assertFalse(second.exists());self.assertEqual(list(Path(folder).iterdir()),[])

    def test_new_config_validates_before_write_and_keeps_existing_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.kdl'
            with patch.dict(os.environ,{'NIRI_CONFIG':str(path)}),patch.object(niri,'validate') as validate:
                niri.initial_config('/niri',['foot','--title','a "title"'],Mock(return_value=True))
                text=path.read_text();self.assertIn('Mod+Return',text);self.assertIn('start-menu',text);self.assertNotIn('spawn-at-startup',text);validate.assert_called_once()
                path.unlink();real=Path(folder)/'real.kdl';real.write_text('// existing');path.symlink_to(real)
                confirm=Mock();niri.initial_config('/niri',['foot'],confirm);confirm.assert_not_called()
                self.assertTrue(path.is_symlink());self.assertEqual(real.read_text(),'// existing')

    def test_invalid_new_config_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.kdl'
            with patch.dict(os.environ,{'NIRI_CONFIG':str(path)}),patch.object(niri,'validate',side_effect=RuntimeError('invalid')):
                with self.assertRaises(RuntimeError):niri.initial_config('/niri',['foot'],Mock(return_value=True))
                self.assertFalse(path.exists())

    def test_session_packages_skip_installed_and_unknown_optional_components(self):
        names=['xdg-desktop-portal','xdg-desktop-portal-gnome','xdg-desktop-portal-gtk','gnome-keyring']
        with patch.object(niri,'installed_packages',return_value=set(names)),patch.object(niri,'package_candidates',return_value={}),patch('adws_launcher.terminal_argv',return_value=['kitty']):
            install=Mock();self.assertEqual(niri.session_dependencies('apt-get',Mock(),install),['kitty']);install.assert_not_called()

    def test_existing_rust_environment_never_downloads_or_updates(self):
        def version(command,**kwargs):return completed(Path(command[0]).name+' 1.90.0')
        with patch.object(niri.shutil,'which',side_effect=lambda name,**kw:'/cargo/'+name),patch.object(niri.subprocess,'run',side_effect=version),patch.object(niri.urllib.request,'urlopen') as download:
            confirm=Mock();niri.prepare_rust({'PATH':'/usr/bin','CARGO_HOME':'/cargo'},confirm);confirm.assert_not_called();download.assert_not_called()

    def test_real_niri_accepts_generated_basic_configuration(self):
        import shutil
        binary=shutil.which('niri')
        if not binary:self.skipTest('niri not installed')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIRI_CONFIG':str(Path(folder)/'config.kdl')}):
            niri.initial_config(binary,['/usr/bin/foot'],Mock(return_value=True))

if __name__=='__main__':unittest.main()

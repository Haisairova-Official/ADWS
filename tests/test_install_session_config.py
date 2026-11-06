import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_session_config as session


class SessionConfigTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.config=self.root/'config';self.niri=self.config/'niri/config.kdl'
        self.niri.parent.mkdir(parents=True);self.niri.write_text('// personal config\n')
        self.features={'features':[{'id':'input','provider':None},{'id':'audio'},{'id':'preview'},
            {'id':'notifications','provider':None},{'id':'lock','provider':None},{'id':'clipboard'}]}
        self.units={name:'disabled' for name in session.UNITS}
        self.which=lambda name:None if name in ('pulseaudio','pipewire-media-session') else '/usr/bin/'+name
    def plan(self,**kw):
        args={'environ':{},'which':self.which,'units':self.units};args.update(kw)
        return session.plan(self.config,self.features,self.niri,**args)

    def test_niri_environment_and_executable_commands_without_global_gtk_override(self):
        before=self.niri.read_bytes();proposal=self.plan()
        self.assertEqual(self.niri.read_bytes(),before)
        self.assertEqual(proposal['environment']['XMODIFIERS'],'@im=fcitx')
        self.assertNotIn('GTK_IM_MODULE',proposal['environment'])
        self.assertEqual(proposal['startup_commands']['input-method'][0],'env')
        self.assertEqual(proposal['startup_commands']['input-method'][-1],'fcitx5')
        self.assertIn('QT_IM_MODULES=wayland;fcitx',proposal['startup_commands']['clipboard-text'])
        self.assertEqual(proposal['lock_argv'],['swaylock'])
        self.assertFalse(Path(proposal['env_file']).exists())

    def test_user_env_conflict_is_reported_not_overwritten(self):
        self.niri.write_text('environment { QT_IM_MODULE "ibus"; XMODIFIERS null; }\n')
        proposal=self.plan(environ={'GTK_IM_MODULE':'fcitx'})
        self.assertEqual({row['kind'] for row in proposal['conflicts']},{'input-environment','gtk-wayland-override'})
        self.assertEqual(self.niri.read_text(),'environment { QT_IM_MODULE "ibus"; XMODIFIERS null; }\n')
        with self.assertRaises(ValueError):session.apply(proposal,self.root/'backup',Mock(),which=self.which,units=self.units)

    def test_quoted_semicolon_and_includes_are_scanned(self):
        other=self.niri.parent/'input.kdl';other.write_text('environment { QT_IM_MODULES "wayland;fcitx"; QT_IM_MODULE "fcitx"; }\n')
        self.niri.write_text('include "input.kdl"\n')
        proposal=self.plan()
        self.assertFalse(proposal['conflicts'])
        self.assertIn(str(other.resolve()),proposal['source_hashes'])
        other.write_text('environment { QT_IM_MODULE "ibus"; }\n')
        with self.assertRaisesRegex(ValueError,'changed after review'):
            session.apply(proposal,self.root/'backup',Mock(),which=self.which,units=self.units)

    def test_existing_ibus_pulseaudio_and_media_session_preserved(self):
        self.features['features'][0]['provider']='ibus-daemon'
        which=lambda name: '/usr/bin/'+name if name in ('ibus-daemon','pulseaudio','pipewire-media-session') else None
        proposal=self.plan(which=which)
        self.assertEqual(proposal['environment'],{})
        self.assertEqual(proposal['startup_commands']['input-method'],['ibus-daemon','--daemonize','--xim'])
        chosen={row['unit'] for row in proposal['service_actions']}
        self.assertIn('pulseaudio.socket',chosen)
        self.assertIn('pipewire-media-session.service',chosen)
        self.assertNotIn('pipewire-pulse.socket',chosen)
        self.assertNotIn('wireplumber.service',chosen)

    def test_masked_or_competing_services_block(self):
        self.units['pipewire.socket']='masked'
        self.units['pulseaudio.socket']='enabled'
        self.units['pipewire-pulse.socket']='enabled'
        kinds={row['kind'] for row in self.plan()['conflicts']}
        self.assertIn('audio-providers',kinds)
        self.assertIn('masked-service',kinds)

    def test_apply_writes_fragment_validates_and_enables_only_next_login(self):
        proposal=self.plan();seen=[]
        def run(argv,**kwargs):
            self.assertNotIn('--now',argv);self.assertNotIn('start',argv);self.assertNotIn('restart',argv)
            self.assertEqual(kwargs['env']['XDG_CONFIG_HOME'],str(self.config))
            self.units[argv[-1]]='enabled';seen.append(argv)
            return subprocess.CompletedProcess(argv,0)
        def validate(path): self.assertIn('environment {',path.read_text())
        result=session.apply(proposal,self.root/'backup',validate,run=run,which=self.which,units=self.units)
        self.assertEqual(result['activation'],'next_login')
        self.assertEqual(Path(proposal['env_file']).read_text(),proposal['env_kdl'])
        self.assertEqual(self.niri.read_text(),'// personal config\n')
        self.assertEqual(len(seen),3)
        self.assertTrue((self.root/'backup/plan.json').exists())

    def test_missing_executable_and_unit_fail_before_writes(self):
        proposal=self.plan()
        with self.assertRaisesRegex(RuntimeError,'commands are not installed'):
            session.apply(proposal,self.root/'backup',Mock(),which=lambda _:None,units=self.units)
        self.assertFalse(Path(proposal['env_file']).exists())
        self.units['wireplumber.service']='unavailable'
        with self.assertRaisesRegex(RuntimeError,'unavailable or masked'):
            session.apply(proposal,self.root/'backup',Mock(),which=self.which,units=self.units)
        self.assertFalse(Path(proposal['env_file']).exists())

    def test_validator_rejection_does_not_modify_file_or_enable_services(self):
        proposal=self.plan();run=Mock()
        with self.assertRaisesRegex(ValueError,'bad KDL'):
            session.apply(proposal,self.root/'backup',Mock(side_effect=ValueError('bad KDL')),run=run,which=self.which,units=self.units)
        run.assert_not_called();self.assertFalse(Path(proposal['env_file']).exists())

    def test_success_exit_without_persistent_enablement_is_failure(self):
        proposal=self.plan()
        with self.assertRaisesRegex(RuntimeError,'did not persist'):
            session.apply(proposal,self.root/'backup',Mock(),run=Mock(),which=self.which,units=self.units)

    def test_unit_state_inspection_is_filesystem_only(self):
        folder=self.config/'systemd/user';folder.mkdir(parents=True)
        definition=folder/'pipewire.socket';definition.write_text('[Install]\nWantedBy=sockets.target\n')
        wants=folder/'sockets.target.wants';wants.mkdir();(wants/'pipewire.socket').symlink_to(definition)
        (folder/'pipewire-pulse.socket').symlink_to('/dev/null')
        states=session.unit_states(self.config,unit_dirs=[folder])
        self.assertEqual(states['pipewire.socket'],'enabled')
        self.assertEqual(states['pipewire-pulse.socket'],'masked')
        self.assertEqual(states['wireplumber.service'],'unavailable')

    def test_fresh_chinese_profile_requires_real_engine_and_preserves_user_profile(self):
        features={'mode':'fresh','features':[{'id':'input','provider':'fcitx5'}]}
        env={'LANG':'zh_CN.UTF-8','XDG_DATA_HOME':str(self.root/'data'),'XDG_DATA_DIRS':str(self.root/'empty')}
        proposal=session.plan(self.config,features,self.niri,environ=env,which=self.which,units={})
        self.assertEqual(len(proposal['profile_writes']),1)
        with self.assertRaisesRegex(RuntimeError,'Pinyin'):
            session.apply(proposal,self.root/'failed-backup',Mock(),which=self.which,units={})
        engine=self.root/'data/fcitx5/inputmethod/pinyin.conf';engine.parent.mkdir(parents=True);engine.write_text('[InputMethod]\nName=Pinyin\n')
        session.apply(proposal,self.root/'backup',Mock(),which=self.which,units={})
        profile=self.config/'fcitx5/profile'
        self.assertIn('DefaultIM=pinyin',profile.read_text())
        profile.write_text('my custom mozc group')
        updated=session.plan(self.config,features,self.niri,environ=env,which=self.which,units={})
        self.assertEqual(updated['profile_writes'],[])
        self.assertEqual(profile.read_text(),'my custom mozc group')

    def test_reinstall_preserves_edited_managed_environment(self):
        first=self.plan()
        path=Path(first['env_file']);path.parent.mkdir(parents=True)
        path.write_text(first['env_kdl'])
        self.niri.write_text(first['include_line']+'\n')
        self.assertFalse(self.plan()['conflicts'])
        edited=path.read_text().replace('QT_IM_MODULE "fcitx"','QT_IM_MODULE "ibus"')
        path.write_text(edited)
        second=self.plan()
        self.assertIn('modified-managed-session',{row['kind'] for row in second['conflicts']})
        with self.assertRaisesRegex(ValueError,'conflicts'):
            session.apply(second,self.root/'backup',Mock(),which=self.which,units=self.units)
        self.assertEqual(path.read_text(),edited)

    def test_legacy_generated_fragment_is_migratable_but_personal_fragment_is_not(self):
        path=self.config/'adws/niri-session.kdl';path.parent.mkdir(parents=True)
        path.write_text(session.environment_text(session.FCITX_ENVIRONMENT,stamped=False))
        proposal=self.plan()
        self.assertFalse(proposal['conflicts'])
        self.assertTrue(proposal['env_kdl'].startswith(session.SESSION_HASH))
        path.write_text('// personal overrides\nenvironment { QT_IM_MODULE "ibus"; }\n')
        self.assertIn('modified-managed-session',{row['kind'] for row in self.plan()['conflicts']})

if __name__=='__main__':unittest.main()

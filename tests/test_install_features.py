import sys
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_features as features
READY_FONTS={'status':'ready','missing':{'zh':'','ja':'','ko':''}}


class FeatureManifestTests(unittest.TestCase):
    def setUp(self):
        probe=patch('adws_fonts.probe_text_fonts',return_value=READY_FONTS);probe.start();self.addCleanup(probe.stop)

    def test_text_font_gaps_add_reviewed_dependencies_in_every_mode_and_locale(self):
        missing={'status':'missing','missing':{'zh':'中','ja':'ひ','ko':'한'}}
        for manager,package in [('pacman','noto-fonts-cjk'),('apt-get','fonts-noto-cjk'),('dnf','google-noto-sans-cjk-vf-fonts')]:
            for mode in ('fresh','integrate','migrate'):
                with self.subTest(manager=manager,mode=mode),patch.dict('os.environ',{'LANG':'en_US.UTF-8'}):
                    plan=features.feature_plan(mode,manager,['taskbar'],which=lambda _:None,font_probe=lambda:missing)
                    self.assertIn(package,plan['packages']);self.assertEqual(plan['text_fonts']['coverage'],missing)
                    covered=features.feature_plan(mode,manager,['taskbar'],which=lambda _:None,font_probe=lambda:READY_FONTS)
                    self.assertNotIn(package,covered['packages']);self.assertEqual(covered['text_fonts']['packages'],[])

    def test_modes_have_distinct_configuration_ownership(self):
        configurations = {features.feature_plan(mode, 'pacman', [], which=lambda _: None)['configuration']
                          for mode in ('fresh', 'integrate', 'migrate')}
        self.assertEqual(len(configurations), 3)
        with self.assertRaises(ValueError): features.feature_plan('overwrite', 'pacman')
        with self.assertRaises(ValueError): features.feature_plan('fresh', 'unknown')
        with self.assertRaises(ValueError): features.feature_plan('fresh', 'pacman', ['typo'])

    def test_every_requested_feature_has_packages_configs_services_and_acceptance(self):
        self.assertEqual(set(features.FEATURE_MANIFEST), {'taskbar', 'preview', 'screenshot', 'clipboard',
            'input', 'audio', 'brightness', 'notifications', 'lock', 'wallpaper', 'palette'})
        for manager in features.MANAGERS:
            plan = features.feature_plan('fresh', manager, which=lambda _: None)
            self.assertEqual(len(plan['packages']), len(set(plan['packages'])))
            self.assertTrue(plan['requires_repository_resolution'])
            for row in plan['features']:
                self.assertTrue(row['packages'])
                self.assertIsInstance(row['configs'], list)
                self.assertIsInstance(row['services'], list)
                self.assertTrue(row['acceptance'])

    def test_existing_providers_are_not_replaced(self):
        installed = {'ibus-daemon', 'pipewire-media-session', 'pulseaudio', 'dunst', 'hyprlock', 'swww'}
        which = lambda name: '/usr/bin/' + name if name in installed else None
        plan = features.feature_plan('integrate', 'pacman', which=which)
        for forbidden in ('wireplumber', 'pipewire-pulse', 'mako', 'swaylock', 'swaybg', 'fcitx5'):
            self.assertNotIn(forbidden, plan['packages'])
        self.assertEqual(next(row for row in plan['features'] if row['id']=='input')['provider'], 'ibus-daemon')

    def test_fresh_audio_needs_server_but_does_not_replace_existing(self):
        plan = features.feature_plan('fresh', 'pacman', ['audio'], which=lambda _: None)
        self.assertIn('pipewire-pulse', plan['packages'])
        plan = features.feature_plan('fresh', 'pacman', ['audio'], which=lambda name: name if name=='pulseaudio' else None)
        self.assertNotIn('pipewire-pulse', plan['packages'])

    def test_fcitx_frontends_are_included_without_duplicate_autostart(self):
        for manager in features.MANAGERS:
            plan = features.feature_plan('fresh', manager, ['input'], which=lambda _: None)
            self.assertIn('fcitx5', plan['packages'])
            self.assertNotIn('fcitx5-autostart', plan['packages'])
            self.assertTrue(any('gtk' in package for package in plan['packages']))
            self.assertTrue(any('qt' in package for package in plan['packages']))

    def test_readiness_never_claims_functional_acceptance(self):
        with patch('adws_runtime_dependencies.missing_dependencies', return_value={'preview':['pngenc']}):
            result = features.probe_features(['preview', 'clipboard'], which=lambda name: name)
        self.assertEqual(result['preview']['status'], 'missing')
        self.assertIn('pngenc', result['preview']['missing'])
        self.assertEqual(result['clipboard']['status'], 'ready')
        self.assertEqual(result['clipboard']['acceptance'], 'pending')

    def test_legacy_runtime_lists_share_inventory(self):
        legacy = features.legacy_runtime_packages()
        self.assertEqual(legacy['pacman']['preview'], features.FEATURE_MANIFEST['preview']['packages']['pacman'])
        self.assertNotIn('wireplumber', legacy['pacman']['preview'])
        self.assertEqual(legacy['pacman']['preview-session'], ['wireplumber'])


class ConfiguredProviderTests(unittest.TestCase):
    def setUp(self):
        probe=patch('adws_fonts.probe_text_fonts',return_value=READY_FONTS);probe.start();self.addCleanup(probe.stop)
        temporary=tempfile.TemporaryDirectory(prefix='adws-provider-test-');self.addCleanup(temporary.cleanup)
        self.config=Path(temporary.name)/'config';self.config.mkdir()
        self.niri=self.config/'niri/config.kdl';self.niri.parent.mkdir();self.niri.write_text('input {}\n')
        self.autostart=self.config/'autostart';self.autostart.mkdir()
        self.units=self.config/'systemd/user';self.units.mkdir(parents=True)
        self.options={'unit_dirs':[self.units],'autostart_dirs':[self.autostart]}
        self.which=lambda name:'/usr/bin/'+name

    def hints(self,environ=None):
        return features.provider_hints(self.config,self.niri,environ=environ or {},audit_options=self.options)

    def plan(self,selected,environ=None):
        return features.feature_plan('integrate','pacman',selected,which=self.which,provider_hints=self.hints(environ))

    def test_configured_ibus_wins_over_installed_fcitx(self):
        self.niri.write_text('spawn-at-startup "ibus-daemon" "--xim"\n')
        result=self.plan(['input']);self.assertFalse(result['conflicts'])
        self.assertEqual(result['features'][0]['provider'],'ibus-daemon')
        self.assertEqual(result['features'][0]['provider_policy'],'preserve-configured')
        self.assertNotIn('fcitx5',result['packages'])
        # This is provenance for pre-mutation revalidation, not live service proof.
        self.assertEqual(result['provider_hints']['source_hashes'][str(self.niri)],hashlib.sha256(self.niri.read_bytes()).hexdigest())
        from adws_install_session_config import plan as session_plan
        session=session_plan(self.config,result,self.niri,environ={},which=self.which,units={})
        self.assertEqual(session['input_provider'],'ibus-daemon')
        self.assertEqual(session['environment'],{},'do not prefix an IBus session with Fcitx frontends')
        self.assertFalse(session['conflicts'])

    def test_existing_niri_frontend_environment_is_authoritative(self):
        self.niri.write_text('environment { XMODIFIERS "@im=ibus"; QT_IM_MODULE "ibus"; }\n')
        result=self.plan(['input'],{'XMODIFIERS':'@im=fcitx','QT_IM_MODULE':'fcitx'})
        self.assertFalse(result['conflicts']);self.assertEqual(result['features'][0]['provider'],'ibus-daemon')
        self.assertNotIn('fcitx5',result['packages'])

    def test_environment_and_owner_conflicts_do_not_switch_providers(self):
        self.niri.write_text('spawn-at-startup "fcitx5"\nenvironment { XMODIFIERS "@im=ibus"; }\n')
        result=self.plan(['input'])
        self.assertTrue(any(row['kind']=='input-environment-owner-conflict' for row in result['conflicts']))
        self.assertIsNone(result['features'][0]['provider']);self.assertEqual(result['packages'],[])

    def test_duplicate_owners_require_review_even_for_same_provider(self):
        self.niri.write_text('spawn-at-startup "ibus-daemon"\n')
        (self.autostart/'ibus.desktop').write_text('[Desktop Entry]\nType=Application\nExec=ibus-daemon\n')
        result=self.plan(['input']);self.assertTrue(result['conflicts'])
        self.assertIsNone(result['features'][0]['provider']);self.assertEqual(result['packages'],[])

    def test_notification_xdg_owner_wins_over_installed_mako(self):
        (self.autostart/'notifications.desktop').write_text('[Desktop Entry]\nType=Application\nExec=dunst\nOnlyShowIn=niri;\n')
        result=self.plan(['notifications']);self.assertFalse(result['conflicts'])
        self.assertEqual(result['features'][0]['provider'],'dunst');self.assertNotIn('mako',result['packages'])

    def test_wallpaper_enabled_service_wins_over_installed_order(self):
        service=self.units/'wallpaper.service';service.write_text('[Service]\nExecStart=/usr/bin/swww-daemon\n')
        wants=self.units/'graphical-session.target.wants';wants.mkdir();(wants/service.name).symlink_to(service)
        result=self.plan(['wallpaper']);self.assertFalse(result['conflicts'])
        self.assertEqual(result['features'][0]['provider'],'swww');self.assertEqual(result['packages'],[])
        self.assertIn(str(service),result['provider_hints']['source_hashes'])

    def test_wallpaper_client_commands_are_not_duplicate_daemon_owners(self):
        self.niri.write_text('spawn-at-startup "swww-daemon"\nspawn-at-startup "swww" "img" "/test.png"\n')
        result=self.plan(['wallpaper']);self.assertFalse(result['conflicts'])
        self.assertEqual(result['features'][0]['provider'],'swww')

    def test_multiple_input_frontend_families_require_review(self):
        result=self.plan(['input'],{'XMODIFIERS':'@im=ibus','QT_IM_MODULES':'wayland;fcitx'})
        self.assertTrue(result['conflicts']);self.assertEqual(result['packages'],[])

    def test_included_ibus_environment_and_hidden_fcitx_owner(self):
        included=self.niri.parent/'input.kdl';included.write_text('environment { XMODIFIERS "@im=ibus"; }\n')
        self.niri.write_text('include "input.kdl"\ninclude optional=true "absent.kdl"\n')
        (self.autostart/'fcitx.desktop').write_text('[Desktop Entry]\nType=Application\nExec=fcitx5\nHidden=true\n')
        result=self.plan(['input']);self.assertFalse(result['conflicts'])
        self.assertEqual(result['features'][0]['provider'],'ibus-daemon')
        self.assertIn(str(included),result['provider_hints']['source_hashes'])

    def test_missing_configured_program_is_not_replaced(self):
        self.niri.write_text('spawn-at-startup "ibus-daemon"\n')
        self.which=lambda name:'/usr/bin/fcitx5' if name=='fcitx5' else None
        result=self.plan(['input']);self.assertEqual(result['conflicts'][0]['kind'],'configured-provider-unavailable')
        self.assertEqual(result['packages'],[]);self.assertIsNone(result['features'][0]['provider'])

    def test_empty_fresh_hints_preserve_current_default(self):
        result=features.feature_plan('fresh','pacman',['input','notifications','wallpaper'],which=lambda _:None,provider_hints=self.hints())
        self.assertFalse(result['conflicts'])
        for expected in ('fcitx5','mako','swaybg'):self.assertIn(expected,result['packages'])


if __name__ == '__main__': unittest.main()

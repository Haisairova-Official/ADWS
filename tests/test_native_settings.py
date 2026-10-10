"""Native settings contracts. All service writes are mocked; no live changes."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0')
from gi.repository import GLib
import adws_native_services as native
import adws_native_accounts as accounts
import adws_native_bluetooth as bluetooth
import adws_power_policy as power
import adws_privileged_settings as privileged


def reply(data):return GLib.Variant('(a{sa{sv}})',(data,))


class NativeContracts(unittest.TestCase):
    def setUp(self):
        # Any accidental unmocked service call fails before it reaches the host.
        for module,names in [(native,['bus_call','command']),(accounts,['bus_call','properties']),(bluetooth,['bus_call'])]:
            for name in names:
                guard=patch.object(module,name,side_effect=AssertionError('Unmocked service operation'))
                guard.start();self.addCleanup(guard.stop)

    def test_ip_validation_happens_before_service_calls(self):
        for args in [(4,'manual',''),(4,'auto','2001:db8::1/64'),(6,'auto','','1.1.1.1'),(4,'auto','','','::1'),(4,'invented','')]:
            with self.assertRaises(ValueError):native.ip_settings(*args)
        native.bus_call.assert_not_called()

    def test_ip_encodes_precise_dbus_types(self):
        result=native.ip_settings(4,'manual','192.0.2.7/24','192.0.2.1','1.1.1.1, 9.9.9.9')
        self.assertEqual(result['address-data'].get_type_string(),'aa{sv}')
        self.assertEqual(result['address-data'].unpack(),[{'address':'192.0.2.7','prefix':24}])
        self.assertEqual(result['dns-data'].unpack(),['1.1.1.1','9.9.9.9'])
        self.assertTrue(result['ignore-auto-dns'].unpack())

    def test_wifi_passwords_never_enter_command_arguments(self):
        secret='pass$(NOT_A_COMMAND)'
        result=native.wifi_settings('Home','Home','wpa-psk',secret)
        self.assertEqual(result['802-11-wireless-security']['psk'].unpack(),secret)
        self.assertEqual(result['connection']['permissions'].get_type_string(),'as')
        native.command.assert_not_called();native.bus_call.assert_not_called()
        for password in ('short','x'*65):
            with self.assertRaises(ValueError):native.wifi_settings('Home','Home','wpa-psk',password)
        with self.assertRaises(ValueError):native.wifi_settings('Home','x'*33,'open')

    def test_wep_and_open_networks(self):
        self.assertNotIn('802-11-wireless-security',native.wifi_settings('Open','Open','open'))
        result=native.wifi_settings('Old','Old','wep','ABCDE')
        self.assertEqual(result['802-11-wireless-security']['key-mgmt'].unpack(),'none')
        with self.assertRaises(ValueError):native.wifi_settings('Old','Old','wep','ABC')

    def test_enterprise_tls_certificates_and_no_password_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate=Path(directory)/'server CA.pem';certificate.write_text('fixture')
            client=Path(directory)/'client.pem';client.write_text('fixture')
            private=Path(directory)/'client.key';private.write_text('fixture')
            result=native.wifi_settings('Work','Work','enterprise',identity='user',ca=str(certificate),eap='tls',client=str(client),private_key=str(private),key_password='private secret')
            auth=result['802-1x']
            self.assertTrue(bytes(auth['ca-cert'].unpack()).endswith(b'\0'))
            self.assertEqual(auth['private-key-password'].unpack(),'private secret')
            self.assertNotIn('phase2-auth',auth)
        with self.assertRaises(ValueError):native.wifi_settings('Work','Work','enterprise','password','user','/missing.pem')

    def test_credentials_and_unedited_vpn_secrets_survive_update(self):
        current={'connection':{'id':GLib.Variant('s','VPN')},'vpn':{'data':GLib.Variant('a{ss}',{'remote':'vpn.example'})},'ipv4':{'dns':GLib.Variant('au',[1]),'addresses':GLib.Variant('aau',[[1,24,2]])}}
        profile={'path':native.NM_SETTINGS+'/1','settings':current}
        secrets={'vpn':{'secrets':GLib.Variant('a{ss}',{'password':'old','private-key-password':'retain'})}}
        with patch.object(native,'bus_call',side_effect=[reply(current),reply(secrets),GLib.Variant('(a{sv})',({},))]) as call:
            native.nm_update(profile,{'vpn':{'secrets':GLib.Variant('a{ss}',{'password':'new'})},'ipv4':native.ip_settings(4,'auto')|{'address-data':GLib.Variant('aa{sv}',[])}})
        candidate=call.call_args.args[5][0]
        self.assertEqual(candidate['vpn']['secrets'].unpack(),{'password':'new','private-key-password':'retain'})
        self.assertNotIn('dns',candidate['ipv4']);self.assertNotIn('addresses',candidate['ipv4'])
        self.assertEqual(profile['settings'],current)

    def test_conflicting_network_edit_never_writes(self):
        current={'connection':{'id':GLib.Variant('s','other')}}
        with patch.object(native,'bus_call',return_value=reply(current)) as call:
            with self.assertRaises(RuntimeError):native.nm_update({'path':native.NM_SETTINGS+'/1','settings':{}},{})
        self.assertEqual(call.call_count,1)

    def test_failed_secret_read_does_not_erase_credentials(self):
        current={'connection':{},'vpn':{}}
        with patch.object(native,'bus_call',side_effect=[reply(current),RuntimeError('denied')]) as call:
            with self.assertRaises(RuntimeError):native.nm_update({'path':native.NM_SETTINGS+'/1','settings':current},{})
        self.assertEqual(call.call_count,2)

    def test_failed_activation_keeps_created_profile(self):
        with patch.object(native,'bus_call',side_effect=[GLib.Variant('(oa{sv})',(native.NM_SETTINGS+'/1',{})),RuntimeError('activation failed')]) as call:
            with self.assertRaises(RuntimeError):native.nm_create({'connection':{}})
        self.assertEqual([c.args[3] for c in call.call_args_list],['AddConnection2','ActivateConnection'])

    def test_vpn_path_is_one_argument(self):
        with tempfile.TemporaryDirectory(prefix='vpn $(fixture) ') as directory:
            path=Path(directory)/'profile.conf';path.write_text('fixture')
            with patch.object(native,'command',return_value='') as run:native.vpn_import('wireguard',str(path))
            self.assertEqual(run.call_args.args[0][-1],str(path))
            with self.assertRaises(ValueError):native.vpn_import('--invalid',str(path))

    def test_audio_rejects_invalid_types_and_nonfinite_values(self):
        for value in (math.nan,math.inf,-1,101,True,'50'):
            with self.assertRaises(ValueError):native.audio_set('sink-input',1,'volume',value)
        for args in [('sink',1,'channels',[math.inf]),('sink',1,'port','--invalid'),('card',1,'profile','p;sh'),('sink-input',True,'mute',False),('source-output',1,'move',-1)]:
            with self.assertRaises(ValueError):native.audio_set(*args)
        native.command.assert_not_called()

    def test_audio_routes_capture_and_multichannel_precisely(self):
        with patch.object(native,'command') as run:
            native.audio_set('source-output',3,'move',5)
            self.assertEqual(run.call_args.args[0],['pactl','move-source-output','3','5'])
            native.audio_set('sink',2,'channels',[35,60])
            self.assertEqual(run.call_args.args[0][-2:],['35%','60%'])

    def test_bluetooth_device_cannot_escape_selected_adapter(self):
        with self.assertRaises(ValueError):bluetooth.action('/org/bluez/hci0','/org/bluez/hci1/dev_AB_CD_EF_01_02_03','Connect')
        bluetooth.bus_call.assert_not_called()

    def test_agent_rejects_unauthorized_requests(self):
        agent=bluetooth.PairingAgent.__new__(bluetooth.PairingAgent)
        agent.closed=False;agent.owner=':1.4';agent.device='/org/bluez/hci0/dev_AB_CD_EF_01_02_03'
        invocation=Mock()
        agent.method(None,':1.99',bluetooth.PATH,'org.bluez.Agent1','RequestConfirmation',GLib.Variant('(ou)',(agent.device,123456)),invocation)
        invocation.return_dbus_error.assert_called_once();invocation.return_value.assert_not_called()

    def test_agent_registration_finishing_after_close_is_cleaned(self):
        agent=bluetooth.PairingAgent.__new__(bluetooth.PairingAgent)
        agent.closed=True;agent.registered=False;agent.unregister=Mock();agent.call=Mock();agent.finish=Mock()
        agent.ready(Mock(),Mock(),None)
        agent.unregister.assert_called_once();agent.call.assert_not_called()

    def test_fcitx_variant_tree_and_config_conflict(self):
        from adws_native_input import raw_variant
        value=raw_variant({'Hotkey':{'TriggerKeys':{'0':'Control+space'}},'Behavior':{'Show': 'True'}})
        self.assertEqual(value.get_type_string(),'a{sv}')
        self.assertEqual(value.unpack()['Behavior'],{'Show':'True'})
        for invalid in (True,123,[],None):
            with self.assertRaises(ValueError):raw_variant(invalid)
        expected=GLib.Variant('v',raw_variant({'old':'value'}))
        with patch.object(native,'fcitx_config',return_value=GLib.Variant('(v)',(raw_variant({'new':'value'}),))),patch.object(native,'fcitx_call') as write:
            with self.assertRaises(RuntimeError):native.fcitx_set_config('fcitx://config/global',expected,value)
            write.assert_not_called()

    def test_fcitx_keeps_at_least_one_valid_input_method(self):
        current={'group':'default','enabled':[('keyboard-us','')],'layout':'us','available':[('keyboard-us','English')]}
        with patch.object(native,'fcitx_snapshot',return_value=current),patch.object(native,'fcitx_call') as write:
            for names in ([],[('missing','')],[('keyboard-us',''),('keyboard-us','')]):
                with self.assertRaises(ValueError):native.fcitx_set_group(current,names)
            write.assert_not_called()

    def test_account_invalid_edit_cannot_partially_change_name(self):
        current={'Uid':os.getuid(),'RealName':'User','AccountType':1,'Locked':False,'path':accounts.ROOT+'/User'+str(os.getuid())}
        with patch.object(accounts,'properties',return_value=current):
            with self.assertRaises(ValueError):accounts.edit_user(current,{'name':'New','type':False})
        accounts.bus_call.assert_not_called()

    def test_account_failure_restores_reversible_changes(self):
        user={'Uid':1001,'RealName':'Old','AccountType':0,'Locked':False,'IconFile':'','path':accounts.ROOT+'/User1001'}
        with patch.object(accounts,'properties',return_value=user),patch.object(accounts,'password_hash',return_value='$6$fixture'),patch.object(accounts,'bus_call',side_effect=[None,RuntimeError('password rejected'),None]) as call:
            with self.assertRaises(RuntimeError):accounts.edit_user(user,{'name':'New','password':'secret'})
        self.assertEqual([c.args[3] for c in call.call_args_list],['SetRealName','SetPassword','SetRealName'])
        self.assertEqual(call.call_args.args[5],('Old',))

    def test_creation_failure_rolls_back_user_without_deleting_home(self):
        with patch.object(accounts,'password_hash',return_value='$6$fixture'),patch.object(accounts,'properties',return_value={'Uid':1001}),patch.object(accounts,'bus_call',side_effect=[GLib.Variant('(o)',(accounts.ROOT+'/User1001',)),RuntimeError('password failed'),None]) as call:
            with self.assertRaises(RuntimeError):accounts.create_user('newuser','New user',False,'secret')
        self.assertEqual(call.call_args.args[3],'DeleteUser');self.assertEqual(call.call_args.args[5],(1001,False))

    def test_protected_account_cannot_be_deleted_or_disabled(self):
        for uid in (0,999,os.getuid()):
            user={'Uid':uid,'path':accounts.ROOT+'/User'+str(uid)}
            with patch.object(accounts,'properties',return_value=user):
                for action in ('delete','locked'):
                    with self.assertRaises(ValueError):accounts.user_change(user,action,True)
        accounts.bus_call.assert_not_called()

    def test_salted_password_hash_uses_system_library(self):
        first=accounts.password_hash('fixture secret');second=accounts.password_hash('fixture secret')
        self.assertNotEqual(first,second);self.assertTrue(first.startswith('$6$rounds=100000$'))
        self.assertNotIn('fixture',first)

    def test_power_policy_disabled_by_default_and_validated(self):
        self.assertFalse(power.defaults()['enabled'])
        for value in (-1,241,True,'10'):
            data=power.defaults();data['ac']['screen']=value
            with self.assertRaises(ValueError):power.validate(data)
        data=power.defaults();data['ac']['suspend']=5
        with self.assertRaises(ValueError):power.validate(data)

    def test_power_save_cancel_and_disabled_does_not_launch(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CONFIG_HOME':directory}),patch.object(power,'launch') as launch,patch.object(power,'stop_all') as stop:
            power.save(power.defaults());launch.assert_not_called();stop.assert_called_once()
            self.assertEqual(power.load(),power.defaults())
            self.assertEqual(power.path().stat().st_mode&0o777,0o600)

    def test_logind_fixed_allowlist_rejects_injected_lines(self):
        values={key:'ignore' for key in privileged.FIELDS}
        self.assertIn('[Login]',privileged.validate(values))
        values['HandleLidSwitch']='ignore\nExecStart=anything'
        with self.assertRaises(ValueError):privileged.validate(values)
        values={'Other': 'ignore'}
        with self.assertRaises(ValueError):privileged.validate(values)

    def test_logind_writer_never_restarts_live_session(self):
        values={key:'ignore' for key in privileged.FIELDS}
        with patch.object(power.subprocess,'run',return_value=Mock(returncode=0,stderr='')) as run:
            power.logind_save(values)
        self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0][:3],['pkexec',sys.executable,'-I'])
        self.assertEqual(json.loads(run.call_args.kwargs['input']),values)

    def test_power_pid_reuse_never_kills_unrelated_process(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_STATE_HOME':directory}),patch.object(power.os,'kill') as kill:
            target=Path(directory)/'adws/power-policy-fixture.json';target.parent.mkdir();target.write_text(json.dumps({'pid':os.getpid(),'start':'incorrect'}))
            power.stop_all();kill.assert_not_called()

    def test_locale_conflict_and_invalid_selection_never_write(self):
        current={'values':{'LANG':'C.UTF-8'},'locales':['C','C.UTF-8']}
        with patch.object(accounts,'locale_snapshot',return_value=current):
            with self.assertRaises(ValueError):accounts.set_locales(current,{'LANG':'invalid','LC_TIME':'C','LC_NUMERIC':'C'})
            with self.assertRaises(RuntimeError):accounts.set_locales({'values':{}},{'LANG':'C','LC_TIME':'C','LC_NUMERIC':'C'})
        accounts.bus_call.assert_not_called()

    def test_manual_clock_does_not_silently_disable_ntp(self):
        with patch.object(accounts,'timezone_snapshot',return_value={'ntp':True}):
            with self.assertRaises(ValueError):accounts.set_time('2026-10-04T12:00:00+08:00')
        accounts.bus_call.assert_not_called()
        for value in ('invalid','2026-10-04T12:00:00'):
            with self.assertRaises(ValueError):accounts.set_time(value)

    def test_manual_clock_encodes_microseconds(self):
        with patch.object(accounts,'timezone_snapshot',return_value={'ntp':False}),patch.object(accounts,'bus_call') as call:
            accounts.set_time('1970-01-01T01:00:00+01:00')
        self.assertEqual(call.call_args.args[5],(0,False,True))

    def test_theme_import_rejects_traversal_and_symlinks(self):
        from adws_native_input import install_theme_archive
        import zipfile
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_DATA_HOME':directory}):
            archive=Path(directory)/'theme.zip'
            for member,mode in [('../escape',0),('/absolute',0),('theme/link',0o120777<<16)]:
                with zipfile.ZipFile(archive,'w') as output:
                    info=zipfile.ZipInfo(member);info.external_attr=mode;output.writestr(info,'fixture')
                with self.assertRaises(ValueError):install_theme_archive(str(archive))
            self.assertFalse((Path(directory)/'escape').exists())
            with zipfile.ZipFile(archive,'w') as output:output.writestr('fixture/theme.conf','[Metadata]\nName=Fixture')
            install_theme_archive(str(archive))
            self.assertTrue((Path(directory)/'fcitx5/themes/fixture/theme.conf').is_file())
            with self.assertRaises(ValueError):install_theme_archive(str(archive))

    def test_power_policy_bundle_is_validated_before_import(self):
        import adws_config_bundle as bundle
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'Config.ad-yml'
            data={'format':'adws-config','version':1,'files':{'adws/power-policy.json':json.dumps(power.defaults())}}
            target.write_text(yaml.safe_dump(data));bundle.read_bundle(target)
            policy=power.defaults();policy['enabled']='yes';data['files']['adws/power-policy.json']=json.dumps(policy)
            target.write_text(yaml.safe_dump(data))
            with self.assertRaises(ValueError):bundle.read_bundle(target)


if __name__=='__main__':unittest.main()

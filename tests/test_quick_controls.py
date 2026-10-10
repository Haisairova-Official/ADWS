"""Real routing/validation with fixture hardware; never changes live devices."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_quick_backend as backend
import adws_quick_controls as controls
import adws_layout as layout

class Controls(unittest.TestCase):
    def test_components_optional_single_and_oriented(self):
        state={'apiVersion':2,'builtins':[{'id':key,'slot':'right'} for key in ('windows','tray','sound','brightness')],'plugins':[], 'options':{'position':'left'}}
        for key in ('tray','sound','brightness'):
            with self.assertRaises(ValueError):layout.new_builtin(key,state['builtins'],{})
        cfg=layout.render_waybar_config(state,[],base={})
        for kind in ('tray','sound','brightness'):
            module=cfg['cffi/system-'+kind]
            self.assertEqual(module['component'],kind);self.assertTrue(module['vertical']);self.assertEqual(module['position'],'left')
        empty=layout.normalize_layout({'apiVersion':2,'builtins':[],'plugins':[]})
        self.assertEqual([r['id'] for r in empty['builtins']],['windows'])
        self.assertTrue(all(not c['repeatable'] and not c['required'] for c in layout.component_catalog([]) if c['key'] in ('tray','brightness','sound')))

    def test_ddc_uses_connector_and_current_maximum(self):
        text='Display 1\n I2C bus: /dev/i2c-5\n DRM connector: card1-DP-2\nDisplay 2\n DRM connector: card1-HDMI-A-1\n'
        self.assertEqual(backend.parse_ddc(text),{'DP-2':1,'HDMI-A-1':2})
        with patch.object(backend,'command') as command,patch.object(backend,'cache_root',return_value=Path('/tmp')):
            backend.brightness_write({'name':'DP-2','provider':'ddc','device':1,'maximum':200},'brightness',50)
            self.assertEqual(command.call_args.args[0],['ddcutil','--display','1','setvcp','10','100'])
            for value in (-1,101,float('nan'),float('inf'),True):
                with self.assertRaises(ValueError):backend.brightness_write({'name':'DP-2'},'brightness',value)
            with self.assertRaises(ValueError):backend.brightness_write({'name':'../../evil'},'brightness',50)

    def test_cached_brightness_is_fast_and_rejects_old_or_invalid_data(self):
        import time
        item={'name':'DP-1','description':'Fixture','provider':'ddc','value':55,
              'temperature':6500,'night':False,'color_provider':None}
        with tempfile.TemporaryDirectory() as name,patch.object(backend,'cache_root',return_value=Path(name)),patch.object(backend,'command') as command:
            path=Path(name)/'brightness-snapshot.json'
            backend.write_json(path,{'time':time.time(),'items':[item]})
            self.assertEqual(backend.cached_brightness(),[item]);command.assert_not_called()
            backend.write_json(path,{'time':time.time()-121,'items':[item]})
            self.assertIsNone(backend.cached_brightness())
            backend.write_json(path,{'time':time.time(),'items':[dict(item,value=float('nan'))]})
            self.assertIsNone(backend.cached_brightness())
            backend.write_json(path,{'time':time.time(),'items':[{'name':'partial'}]})
            self.assertIsNone(backend.cached_brightness())

    def test_ddc_transient_timeout_preserves_last_mapping(self):
        cached={'time':0,'devices':{'DP-1':{'display':1,'bus':4}}}
        with patch.object(backend,'cache_root',return_value=Path('/tmp')),patch.object(backend,'read_json',return_value=cached),patch.object(backend.shutil,'which',return_value='/usr/bin/ddcutil'),patch.object(backend,'command',side_effect=RuntimeError('timeout')) as command,patch.object(backend,'write_json') as write:
            self.assertEqual(backend.ddc_devices(),cached['devices'])
            command.assert_called_once_with(['ddcutil','detect','--terse'],timeout=30)
            write.assert_not_called()

    def test_audio_fallback_and_real_app_volume(self):
        with patch.object(backend,'audio',return_value={'sinks':[]}):
            result=controls.status('sound')
            self.assertFalse(result['available'])
            self.assertEqual(result['state'],'no-device')
            self.assertEqual(result['icon'],'audio-volume-muted-symbolic')
        with patch.object(backend,'audio',return_value={'sinks':[{'default':True,'volume':42,'mute':True}]}):
            data=controls.status('sound');self.assertEqual(data['text'],'42%');self.assertEqual(data['icon'],'audio-volume-muted-symbolic')
        with patch.object(backend,'audio_change') as change:
            backend.audio_write('sink',3,'volume',80);change.assert_called_once_with('sink',3,'volume',80)
        with self.assertRaises(ValueError):backend.audio_write('card',3,'volume',80)

    def test_status_failure_keeps_component_icon_and_error_detail(self):
        import io
        from contextlib import redirect_stdout
        for kind,method,icon in [('sound','audio','audio-volume-high-symbolic'),
                                 ('brightness','brightness','display-brightness-symbolic')]:
            output=io.StringIO()
            with patch.object(sys,'argv',['adws_quick_controls.py',kind,'--status']), \
                 patch.object(backend,method,side_effect=RuntimeError('Connection terminated')),redirect_stdout(output):
                self.assertEqual(controls.main(),1)
            result=json.loads(output.getvalue())
            self.assertEqual(result['icon'],icon)
            self.assertFalse(result['available'])
            self.assertNotEqual(result.get('state'),'no-device')
            self.assertIn('Connection terminated',result['error'])
            self.assertNotEqual(result['error'],'Connection terminated')

    def test_error_explanations_do_not_assume_every_disconnect_is_client_exhaustion(self):
        with patch.object(controls,'tr',side_effect=lambda text:text):
            disconnected=controls.error_message('sound',RuntimeError('Connection failure: Connection terminated'))
            self.assertIn('可能',disconnected)
            self.assertIn('自动检测恢复',disconnected)
            full=controls.error_message('sound',RuntimeError('too many client application connections'))
            self.assertIn('连接数已满',full)
            self.assertIn('技术详情',full)
            self.assertIn('权限',controls.error_message('brightness',PermissionError('Permission denied')))
            self.assertIn('超时',controls.error_message('brightness',RuntimeError('timed out')))

    def test_default_brightness_status_is_average_of_adjustable_outputs(self):
        items=[{'name':'DP-1','provider':'ddc','value':20},
               {'name':'DP-2','provider':'gamma','value':60},
               {'name':'DP-3','provider':None,'value':None}]
        with patch.object(backend,'brightness',return_value=items):
            self.assertEqual(controls.status('brightness')['text'],'40%')
            self.assertEqual(controls.status('brightness','')['text'],'40%')
            self.assertEqual(controls.status('brightness','DP-2')['text'],'60%')
            self.assertFalse(controls.status('brightness','DP-3')['available'])

    def test_parallel_gamma_variants_and_service_errors(self):
        from concurrent.futures import ThreadPoolExecutor
        from gi.repository import GLib
        def call(path, method, args):
            self.assertEqual(args.unpack(), ('rs.wl.gammarelay',))
            if path.endswith('HDMI_A_1'):
                raise GLib.Error('Service unavailable')
            return GLib.Variant('(a{sv})', ({'Temperature':GLib.Variant('q',6500),
                                           'Brightness':GLib.Variant('d',1.0)},))
        with patch.object(backend,'gamma_call',side_effect=call):
            with ThreadPoolExecutor(max_workers=3) as pool:
                states=list(pool.map(backend.gamma_state,['DP-1','DP-2','HDMI-A-1']))
        self.assertEqual([item['brightness'] for item in states[:2]],[100,100])
        self.assertIsNone(states[2])

    def test_night_never_kills_reused_pid(self):
        self.assertFalse(backend.owned_night({'pid':1,'start':'wrong'},'DP-1'))
        with tempfile.TemporaryDirectory() as directory,patch.object(backend,'cache_root',return_value=Path(directory)),patch.object(backend.os,'kill') as kill:
            backend.write_json(backend.night_path('DP-1'),{'pid':1,'start':'wrong','temperature':4000})
            backend.brightness_write({'name':'DP-1','color_provider':'wlsunset'},'night',False)
            kill.assert_not_called();self.assertFalse(backend.night_path('DP-1').exists())

    def test_steps_use_current_default_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(backend,'cache_root',return_value=Path(directory)),patch.object(backend,'audio',return_value={'sinks':[{'default':False,'index':2,'volume':40},{'default':True,'index':9,'volume':99}]}),patch.object(backend,'audio_write') as write:
            backend.step('sound',5);write.assert_called_once_with('sink',9,'volume',100)
            for value in (float('nan'),math.inf,True,1000):
                with self.assertRaises(ValueError):backend.step('sound',value)

if __name__=='__main__':unittest.main()

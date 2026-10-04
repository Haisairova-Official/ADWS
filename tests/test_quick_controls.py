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

    def test_audio_fallback_and_real_app_volume(self):
        with patch.object(backend,'audio',return_value={'sinks':[]}):self.assertFalse(controls.status('sound')['available'])
        with patch.object(backend,'audio',return_value={'sinks':[{'default':True,'volume':42,'mute':True}]}):
            data=controls.status('sound');self.assertEqual(data['text'],'42%');self.assertEqual(data['icon'],'audio-volume-muted-symbolic')
        with patch.object(backend,'audio_change') as change:
            backend.audio_write('sink',3,'volume',80);change.assert_called_once_with('sink',3,'volume',80)
        with self.assertRaises(ValueError):backend.audio_write('card',3,'volume',80)

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

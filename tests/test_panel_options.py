import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from mnws_panel_options import validate, geometry, styles
import mnws_layout as layout

class PanelOptionsTests(unittest.TestCase):
    def test_every_edge_and_two_lanes(self):
        for position in ('top','bottom','left','right'):
            cfg={'height':36,'width':1200}
            options={'position':position,'thickness':64,'window_rows':2,'group_windows':True}
            values, vertical=geometry(cfg,options)
            self.assertEqual(cfg['position'],position)
            self.assertEqual(cfg['width' if vertical else 'height'],64)
            self.assertNotIn('height' if vertical else 'width',cfg)
            result=layout.render_waybar_config({'options':options,'plugins':[], 'builtins':[{'id':'windows','enabled':True,'slot':'left','order':0}]},available=[],base={})
            module=result['cffi/niri-taskbar']
            self.assertEqual(module['rows'],2)
            self.assertEqual(module['vertical'],vertical)
            self.assertTrue(module['group_windows'])
    def test_options_default_and_validation(self):
        self.assertFalse(validate({})['window_animations'])
        self.assertFalse(validate({})['tab_animations'])
        self.assertEqual(validate({'window_rows':2})['thickness'],48)
        for options in [{'position':'diagonal'},{'window_rows':3},{'thickness':-1},{'group_windows':'false'}, {'hover_color':'red; * { opacity:0; }'}]:
            with self.assertRaises(ValueError):validate(options)
    def test_custom_colors_and_transitions(self):
        css=styles({'hover_color':'#112233','focus_color':'rgba(20,40,60,0.5)','window_animations':True,'animation_duration':350})
        self.assertIn('button:hover',css)
        self.assertIn('button.focused',css)
        self.assertIn('350ms',css)
        self.assertIn('#112233',css)
        self.assertIn('transition: none',styles({}))
    def test_orientation_round_trip(self):
        state={'options':{'position':'left','thickness':60},'plugins':[], 'builtins':[]}
        side=layout.render_waybar_config(state,available=[],base={})
        state['options']['position']='top'
        top=layout.render_waybar_config(state,available=[],base=side)
        self.assertNotIn('width',top)
        self.assertEqual(top['height'],60)

    def test_vertical_clock_stays_horizontal_and_keeps_actions(self):
        state={'options':{'position':'left','thickness':48},'plugins':[],
               'builtins':[{'id':'clock','enabled':True,'slot':'right','order':0}]}
        result=layout.render_waybar_config(state,available=[],base={'clock':{'format':'{:%H:%M}','on-click':'kclock','rotate':90}})
        self.assertEqual(result['clock']['rotate'],0)
        self.assertEqual(result['clock']['on-click'],'kclock')
        self.assertEqual(result['clock']['format'],'{:%H:%M}')

    def test_popup_parent_layer_is_above_tiles(self):
        for layer in ('bottom','background','top','overlay'):
            result=layout.render_waybar_config({'options':{},'plugins':[],'builtins':[]},available=[],base={'layer':layer})
            self.assertEqual(result['layer'],'overlay' if layer=='overlay' else 'top')

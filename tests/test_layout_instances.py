"""Layout migration and runtime contracts for independently configured components."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_layout as layout
from adws_launcher import native_menu_command


class LayoutInstancesTests(unittest.TestCase):
    def test_removed_components_stay_absent_and_windows_are_mandatory(self):
        state = {'apiVersion': 2, 'builtins': [], 'plugins': []}
        result = layout.render_waybar_config(state, available=[], base={})
        names = sum([result['modules-'+slot] for slot in ('left','center','right')], [])
        self.assertEqual(names.count('cffi/niri-taskbar'), 1)
        self.assertNotIn('clock', names)
        self.assertNotIn('custom/applauncher', names)
        state['builtins'] = [{'id':'windows','enabled':False}, {'id':'windows','slot':'right'}]
        self.assertEqual(len(layout.normalize_layout(state)['builtins']), 1)
        self.assertTrue(layout.normalize_layout(state)['builtins'][0]['enabled'])

    def test_migrate_idempotently_without_modifying_input(self):
        legacy = {'builtins':[{'id':'start','enabled':False,'slot':'center'}], 'options':{'start_label':'keep'}, 'plugins':[]}
        old = copy.deepcopy(legacy)
        new = layout.normalize_layout(legacy)
        self.assertEqual(legacy, old)
        self.assertEqual(new, layout.normalize_layout(new))
        self.assertFalse(new['builtins'][0]['enabled'])
        self.assertEqual(new['builtins'][0]['instance'], 'start')
        self.assertEqual(len(new['builtins']), 7)

    def test_two_starts_have_separate_commands_icons_slots_and_context_menus(self):
        state = {'apiVersion':2, 'builtins':[
            {'id':'start','instance':'start','slot':'left','options':{'start_label':'One','start_launcher_mode':'adws'}},
            {'id':'start','instance':'start-two','slot':'right','options':{'start_label':'Two','start_launcher_mode':'custom','start_launcher_command':'my-launcher --second'}}], 'plugins':[]}
        result = layout.render_waybar_config(state, available=[], base={})
        self.assertIn('cffi/start-button', result['modules-left'])
        self.assertIn('custom/applauncher#start-two', result['modules-right'])
        one, two = result['cffi/start-button'], result['custom/applauncher#start-two']
        self.assertEqual(one['start_label'], 'One')
        self.assertEqual(one['exec'], native_menu_command())
        self.assertEqual(two['format'], 'Two')
        self.assertEqual(two['on-click'], 'my-launcher --second')
        self.assertIn('adws-config.py', two['on-click-right'])
        self.assertIn('--tab start', two['on-click-right'])
        self.assertIn('--start-instance start-two', two['on-click-right'])
        self.assertIn('--start-instance start', one['start_right_command'])
        for edge in ('top', 'bottom', 'left', 'right'):
            state['options'] = {'position':edge}
            state['builtins'][1]['options']['start_launcher_mode'] = 'adws'
            result = layout.render_waybar_config(state, available=[], base={})
            second = result['cffi/start-button#start-two']
            self.assertEqual(second['start_position'], edge)
            self.assertEqual(second['start_label'], 'Two')

    def test_separate_clocks_and_stale_module_cleanup(self):
        state = {'apiVersion':2,'builtins':[
            {'id':'clock','instance':'clock','options':{'clock':{'show_seconds':False}}},
            {'id':'clock','instance':'clock-second','options':{'clock':{'show_seconds':True,'show_date':True}}}], 'plugins':[]}
        cfg = layout.render_waybar_config(state, available=[], base={'clock#deleted':{'interval':1}, 'cffi/start-button#old':{'start_label':'old'}})
        self.assertEqual(cfg['clock']['interval'],60)
        self.assertEqual(cfg['clock#clock-second']['interval'],1)
        self.assertIn('--instance clock-second',cfg['clock#clock-second']['on-click-right'])
        self.assertNotIn('clock#deleted',cfg)
        self.assertNotIn('cffi/start-button#old',cfg)
        self.assertIn('\n',cfg['clock#clock-second']['format'])

    def test_singletons_and_instance_identity_survive_save(self):
        state = layout.normalize_layout({'apiVersion':2,'builtins':[], 'plugins':[]})
        for _ in range(2):
            state['builtins'].append(layout.new_builtin('start',state['builtins'],{}))
        self.assertEqual(len({row['instance'] for row in state['builtins']}),3)
        for key in ('windows',):
            with self.assertRaises(ValueError):layout.new_builtin(key,state['builtins'],{})
        state['builtins'].append(layout.new_builtin('workspaces',state['builtins'],{}))
        with self.assertRaises(ValueError):layout.new_builtin('workspaces',state['builtins'],{})
        with tempfile.TemporaryDirectory() as directory, patch.object(layout,'PROJECT_LAYOUT_PATH',Path(directory)/'defaults.json'):
            path = Path(directory)/'layout.json'
            layout.save_layout(state,path)
            self.assertEqual(layout.load_layout(path),state)

    def test_plugin_catalog_repeatability_and_removed_configuration_retained(self):
        manifest = {'id':'example.plugin', 'name':'Example'}
        catalog = layout.component_catalog([{'ok':True,'manifest':manifest,'file':Path('/tmp/test.mplg')}])
        self.assertTrue(catalog[-1]['repeatable'])
        state = {'apiVersion':2,'plugins':[{'package':'example.plugin','enabled':False,'settings':{'keep':1}}, {'package':'example.plugin','enabled':True}], 'builtins':[]}
        normalized = layout.normalize_layout(state)
        self.assertEqual(len(normalized['plugins']),2)
        self.assertEqual(normalized['plugins'][0]['settings'],{'keep':1})

    def test_default_regions_and_drag_moves(self):
        data = layout.default_layout()
        self.assertEqual([r['id'] for r in data['builtins'] if r['slot']=='left'],['start','windows'])
        self.assertFalse(any(r['slot']=='center' for r in data['builtins']))
        self.assertEqual([r['id'] for r in data['builtins'] if r['slot']=='right'],['sound','brightness','tray','clock'])
        rows=[{**r,'key':r['id']} for r in data['builtins']]
        self.assertTrue(layout.move_component(rows,'clock','right','sound'))
        self.assertEqual([r['id'] for r in rows if r['slot']=='right'],['clock','sound','brightness','tray'])
        self.assertTrue(layout.move_component(rows,'start','center'))
        self.assertEqual(next(r for r in rows if r['id']=='start')['slot'],'center')
        self.assertFalse(layout.move_component(rows,'windows','left','windows'))
        self.assertTrue(any(r['id']=='windows' for r in rows))
        with tempfile.TemporaryDirectory() as directory:
            restored=layout.load_layout(Path(directory)/'missing.json')
            self.assertEqual(restored['builtins'],data['builtins'])


    def test_user_save_keeps_shipped_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);defaults=root/'defaults.json'
            defaults.write_text('default sentinel')
            with patch.object(layout,'PROJECT_LAYOUT_PATH',defaults):
                layout.save_layout({'apiVersion':2,'builtins':[],'plugins':[],'options':{'private':True}},root/'user.json')
            self.assertEqual(defaults.read_text(),'default sentinel')


    def test_preview_uses_current_per_instance_drafts_and_formats(self):
        from adws_layout_preview import snapshot
        from datetime import datetime
        rows = [{'key':'start','instance':'start','name':'Start','slot':'left','options':{'start_label':'Draft'}},
                {'key':'clock','instance':'clock','name':'Clock','slot':'right','options':{'clock':{'show_seconds':True}}},
                {'key':'clock','instance':'clock-other','name':'Clock','slot':'right','options':{'clock':{'show_date':True,'date_format':'iso'}}},
                {'key':'start','instance':'hidden','name':'Hidden','slot':'left','enabled':False},
                {'key':'windows','instance':'windows','name':'Windows','slot':'center','enabled':False}]
        with patch('subprocess.Popen') as launch:
            result = snapshot(rows,{},datetime(2026,10,4,18,23,45))
            self.assertEqual([item['text'] for item in result[:3]], ['Draft','18:23:45','18:23\n2026-10-04'])
            self.assertEqual(len(result),4)
            self.assertEqual(result[-1]['key'],'windows')
            launch.assert_not_called()

    def test_invalid_instance_cannot_inject_module_or_command(self):
        for identity in ('bad#module','../x','x; touch /tmp/foo','windows',1):
            with self.assertRaises(ValueError):layout.normalize_layout({'apiVersion':2,'builtins':[{'id':'start','instance':identity}]})


if __name__ == '__main__':unittest.main()

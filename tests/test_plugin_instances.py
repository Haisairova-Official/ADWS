"""Manifest repeatability affects validation, layout, commands and storage."""
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_plugin as plugin
import adws_layout as layout

class PluginInstances(unittest.TestCase):
    def setUp(self):
        self.manifest={'id':'org.example.Test','name':'Test','version':'1.0.0','entry':'main.py','renderer':'panel.rows-v1','controls':['play-pause']}

    def test_strict_boolean_for_public_and_legacy_manifests(self):
        legacy={'api':'adws-plugin','apiVersion':1,'kind':'panel','language':'python','interfaces':['panel.rows-v1']}
        for old in (False,True):
            manifest={**self.manifest,**legacy} if old else self.manifest
            if old:manifest.pop('renderer')
            for value in (True,False):self.assertEqual(plugin.validate_manifest({**manifest,'isSingleOnly':value}),[])
            for value in ('true','false',1,0,None,{},[]):
                self.assertTrue(plugin.validate_manifest({**manifest,'isSingleOnly':value}),value)

    def test_default_repeatable_and_singleton_cannot_be_bypassed(self):
        for flag in ({},{'isSingleOnly':False},{'isSingleOnly':True}):
            manifest={**self.manifest,**flag};rows=[]
            first=layout.new_plugin(manifest,rows)
            self.assertEqual(first['instance'],manifest['id'])
            available=[{'ok':True,'manifest':plugin.api1.normalize(manifest),'file':Path('/tmp/test.mplg')}]
            self.assertEqual(layout.component_catalog(available)[-1]['repeatable'],not flag.get('isSingleOnly',False))
            if flag.get('isSingleOnly'):
                with self.assertRaises(ValueError):layout.new_plugin(manifest,rows)
                rows.append({**first,'instance':'another-instance'})
                with self.assertRaises(ValueError):layout.enabled_plugins({'apiVersion':2,'plugins':rows},available)
            else:
                second=layout.new_plugin(manifest,rows);self.assertNotEqual(first['instance'],second['instance']);self.assertEqual(len(rows),2)

    def test_preserve_and_restore_each_removed_instance(self):
        rows=[];first=layout.new_plugin(self.manifest,rows);first['settings']={'color':'red'}
        second=layout.new_plugin(self.manifest,rows);second['settings']={'color':'blue'};first['enabled']=False
        restored=layout.new_plugin(self.manifest,rows)
        self.assertIs(first,restored);self.assertEqual(restored['settings'],{'color':'red'});self.assertEqual(second['settings'],{'color':'blue'})
        state=layout.normalize_layout({'apiVersion':2,'plugins':rows,'builtins':[]})
        self.assertEqual(len(state['plugins']),2)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'layout.json';layout.save_layout(state,path);self.assertEqual(layout.load_layout(path),state)

    def test_distinct_width_commands_and_settings_for_rows_and_text(self):
        for renderer in ('panel.rows-v1','panel.text-v1'):
            manifest=plugin.api1.normalize({**self.manifest,'renderer':renderer})
            rows=[];first=layout.new_plugin(manifest,rows);second=layout.new_plugin(manifest,rows)
            first.update(width=120,settings={'greeting':'first'});second.update(width=240,settings={'greeting':'second'})
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'main.py').write_text('')
                available=[{'ok':True,'manifest':manifest,'file':root/'test.mplg'}]
                with patch.object(layout.mplg,'materialize',return_value=root):
                    cfg=layout.render_waybar_config({'apiVersion':2,'plugins':rows},available,base={})
                entries=layout.enabled_plugins({'apiVersion':2,'plugins':rows},available)
                self.assertNotEqual(entries[0]['module'],entries[1]['module'])
                for entry,greeting in zip(entries,('first','second')):
                    definition=cfg[entry['module']];args=shlex.split(definition['exec'])
                    self.assertEqual(args[:2],['env','ADWS_PLUGIN_INSTANCE='+entry['instance']])
                    self.assertEqual(json.loads(args[-1])['greeting'],greeting)
                    right=definition['right_command' if renderer=='panel.rows-v1' else 'on-click-right']
                    self.assertEqual(shlex.split(right)[-1],manifest['id']+'#'+entry['instance'])
                    if renderer=='panel.rows-v1':
                        self.assertNotIn('#',definition['widget_name'])
                        self.assertEqual(definition['width'],entry['width'])
                        self.assertIn('ADWS_PLUGIN_INSTANCE='+entry['instance'],shlex.split(definition['left_command']))

if __name__=='__main__':unittest.main()

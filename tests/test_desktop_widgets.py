import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import adws_components as components
import adws_desktop_widgets_model as model
import adws_layout as layout
import adws_plugin as mplg


def manifest():
    return {'id':'org.adws.dual','name':'Dual','version':'1.0.0','entry':'bar.py','renderer':'panel.text-v1',
            'components':[{'id':'lyrics','target':'desktop','name':'Desktop lyrics','entry':'desktop.py','renderer':'panel.rows-v1','isSingleOnly':True}]}


class DesktopWidgetTests(unittest.TestCase):
    def test_host_separation_and_legacy_compatibility(self):
        data=manifest()
        self.assertEqual([v['id'] for v in components.components(data,'taskbar')],['org.adws.dual'])
        self.assertEqual([v['id'] for v in components.components(data,'desktop')],['org.adws.dual.lyrics'])
        data.pop('components')
        self.assertEqual(components.components(data,'desktop'),[])
        self.assertEqual(components.select(data)['entry'],'bar.py')

    def test_component_selection_inherits_package_but_not_identity(self):
        data=manifest();data['settingsSchema']=[{'key':'offset','type':'number','min':-10,'max':10,'default':0}]
        child=components.select(data,'lyrics')
        self.assertEqual(child['entry'],'desktop.py');self.assertEqual(child['packageId'],data['id'])
        child['settingsSchema'][0]['default']=5
        self.assertEqual(data['settingsSchema'][0]['default'],0)
        with self.assertRaises(ValueError):components.select(data,'missing')

    def test_bundle_only_manifest_and_explicit_multiple_selection(self):
        data=manifest();del data['entry'];del data['renderer']
        self.assertEqual(mplg.validate_manifest(data,{'desktop.py'}),[])
        self.assertEqual(components.select(data)['componentId'],'lyrics')
        data['components'].append({'id':'clock','target':'taskbar','entry':'bar.py','renderer':'panel.text-v1'})
        with self.assertRaises(ValueError):components.select(data)

    def test_every_component_entry_is_validated(self):
        for field,value in [('entry','../bad.py'),('entry','absent.py'),('renderer','unknown'),('target','anywhere'),('isSingleOnly','true')]:
            data=manifest();data['components'][0][field]=value
            self.assertTrue(mplg.validate_manifest(data,{'bar.py','desktop.py'}),(field,value))
        data=manifest();data['components']*=2
        self.assertTrue(mplg.validate_manifest(data,{'bar.py','desktop.py'}))

    def test_discovery_uses_one_package_version_and_two_host_catalogs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for version in ['1.0.0','1.1.0']:
                data=manifest();data['version']=version
                with zipfile.ZipFile(root/(version+'.mplg'),'w') as z:
                    z.writestr('plugin.json',json.dumps(data));z.writestr('bar.py','');z.writestr('desktop.py','')
            with patch.object(layout,'plugin_dir',return_value=root):
                bar=layout.scan_available_plugins('taskbar');desktop=layout.scan_available_plugins('desktop')
            self.assertEqual(len(bar),1);self.assertEqual(len(desktop),1)
            self.assertEqual(bar[0]['file'],desktop[0]['file']);self.assertEqual(bar[0]['manifest']['version'],'1.1.0')
            self.assertNotEqual(bar[0]['manifest']['id'],desktop[0]['manifest']['id'])
            extracted=mplg.materialize(desktop[0]['file'],root/'cache')
            self.assertTrue((extracted/'desktop.py').is_file())

    def test_layout_is_independent_atomic_and_preserves_notes(self):
        definition={'key':'builtin:note','repeatable':True}
        data=model.add({},definition);data['instances'][0]['settings']={'text':'hello\n你好'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'desktop.json';bar=Path(folder)/'taskbar-layout.json';bar.write_text('unchanged')
            model.save(data,path);self.assertEqual(model.load(path),data);self.assertEqual(bar.read_text(),'unchanged')
            self.assertEqual(list(Path(folder).glob('.desktop-widgets-*')),[])

    def test_singleton_scope_is_per_desktop_component(self):
        definition={'key':'org.adws.dual.lyrics','repeatable':False}
        data=model.add({},definition)
        with self.assertRaises(ValueError):model.add(data,definition)
        data['instances'][0]['enabled']=False
        self.assertEqual(len(model.add(data,definition)['instances']),2)

    def test_geometry_clamps_without_overwriting_saved_output_position(self):
        row=model.add({}, {'key':'builtin:clock'})['instances'][0]
        row.pop('x_percent');row.pop('y_percent')
        row.update(x=9000,y=9000,width=800,height=500)
        self.assertEqual(model.geometry(row,600,400),(0,0,600,400))
        self.assertEqual(row['x'],9000)
        for bad in [float('nan'),True,'100']:
            data={'instances':[{**row,'x':bad}]}
            with self.assertRaises(ValueError):model.normalize(data)

    def test_center_relative_geometry_and_drag_roundtrip(self):
        row=model.add({}, {'key':'builtin:clock'})['instances'][0]
        row.update(width=400,height=200)
        self.assertEqual(model.geometry(row,1920,1080),(760,440,400,200))
        for width,height in [(1280,720),(2560,1440),(3840,2160)]:
            for percent in (-100,0,100):
                row.update(x_percent=percent,y_percent=percent)
                x,y,w,h=model.geometry(row,width,height)
                self.assertEqual((x,y),(round((percent+100)/200*(width-w)),round((percent+100)/200*(height-h))))
                model.move(row,x,y,width,height)
                self.assertAlmostEqual(row['x_percent'],percent)
                self.assertAlmostEqual(row['y_percent'],percent)
        row.update(x_percent=60,y_percent=-40)
        original=copy.deepcopy(row)
        self.assertEqual(model.geometry(row,300,100),(0,0,300,100))
        self.assertEqual(row,original)
        for bad in (float('nan'),float('inf'),True,'10',101,-101):
            with self.assertRaises(ValueError):model.normalize({'instances':[{**row,'x_percent':bad}]})

    def test_legacy_pixel_migration_is_position_preserving(self):
        row=model.add({}, {'key':'builtin:clock'})['instances'][0]
        row.pop('x_percent');row.pop('y_percent');row.update(x=520,y=110,width=360,height=220)
        original=model.geometry(row,1280,800)
        row.update(model.percentages(row,1280,800))
        migrated=model.normalize({'instances':[row]})['instances'][0]
        self.assertNotIn('x',migrated);self.assertNotIn('y',migrated)
        self.assertEqual(model.geometry(migrated,1280,800),original)
        x,y,_,_=model.geometry(migrated,2200,1380)
        self.assertEqual((x,y),(1040,220))

    def test_screen_scope_and_primary_restriction(self):
        row=model.add({}, {'key':'builtin:clock'})['instances'][0]
        self.assertTrue(model.visible_on(row,'screen-a',True))
        self.assertFalse(model.visible_on(row,'screen-b',False))
        row.update(model.scope_values('screen','screen-b',False))
        self.assertTrue(model.visible_on(row,'screen-b',False))
        self.assertFalse(model.visible_on(row,'screen-a',True))
        with self.assertRaises(ValueError):model.scope_values('primary','screen-b',False)
        row.update(model.scope_values('all','screen-b',False))
        self.assertTrue(model.visible_on(row,'screen-a',True))
        self.assertTrue(model.visible_on(row,'screen-b',False))
        row['enabled']=False;self.assertFalse(model.visible_on(row,'screen-a',True))

    def test_mirrors_share_one_plugin_and_independent_read_cursors(self):
        from adws_desktop_plugin import SharedStream
        from unittest.mock import Mock
        source=Mock();source.take.side_effect=[{'primary':'one'},None,{'primary':'two'},None,None]
        closed=Mock();shared=SharedStream(source,closed);first=shared.subscribe();second=shared.subscribe()
        self.assertEqual(first.take(),{'primary':'one'});self.assertEqual(second.take(),{'primary':'one'})
        first.take()['primary']='mutated'
        self.assertEqual(second.take(),{'primary':'two'})
        self.assertIsNone(second.take())
        first.close();source.close.assert_not_called()
        second.event('play');source.event.assert_called_once_with('play',None)
        second.close();second.close();source.close.assert_called_once();closed.assert_called_once()

    def test_malformed_or_excessive_layout_is_not_silently_replaced(self):
        with self.assertRaises(ValueError):model.normalize({'version':99})
        data=model.add({}, {'key':'builtin:clock'})
        data['instances']*=2
        with self.assertRaises(ValueError):model.normalize(data)
        data=model.add({}, {'key':'builtin:note'});data['instances'][0]['settings']={'text':'x'*70000}
        with self.assertRaises(ValueError):model.normalize(data)

    def test_atomic_field_updates_and_singleton_validation(self):
        import concurrent.futures
        data=model.add({}, {'key':'builtin:note'})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'widgets.json';model.save(data,path)
            def edit(key,value):
                def update(data):data['instances'][0][key]=value;return data
                model.mutate(update,path)
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                first=pool.submit(edit,'x_percent',70);second=pool.submit(edit,'locked',True)
                first.result();second.result()
            saved=model.load(path)['instances'][0]
            self.assertEqual(saved['x_percent'],70);self.assertTrue(saved['locked'])
        data=model.add({}, {'key':'org.adws.dual.lyrics'})
        data=model.add(data, {'key':'org.adws.dual.lyrics'})
        with self.assertRaises(ValueError):model.validate_instances(data,[{'key':'org.adws.dual.lyrics','repeatable':False}])
        data=model.add({}, {'key':'builtin:note'});data['instances'][0]['settings']={'text':123}
        with self.assertRaises(ValueError):model.normalize(data)

    def test_duplicates_keep_independent_css_and_settings(self):
        definition={'key':'builtin:note','repeatable':True}
        data=model.add({},definition)
        original=data['instances'][0];original.update(css='.adws-desktop-card { color: red; }',settings={'text':'one'})
        data=model.duplicate(data,original['instance'],[definition])
        first,second=data['instances']
        self.assertNotEqual(first['instance'],second['instance'])
        self.assertEqual(first['css'],second['css'])
        second['settings']['text']='two';second['css']=''
        self.assertEqual(first['settings']['text'],'one');self.assertTrue(first['css'])
        with self.assertRaises(ValueError):model.duplicate(data,first['instance'],[{'key':'builtin:note','repeatable':False}])
        first['css']='x'*65537
        with self.assertRaises(ValueError):model.normalize(data)

    def test_real_netease_bundle_has_independent_lyrics_components(self):
        data=json.loads((ROOT/'plugins/netease-lyrics/plugin.json').read_text())
        self.assertFalse(mplg.validate_manifest(data,{'main.py'}))
        bar=components.components(data,'taskbar');desktop=components.components(data,'desktop')
        self.assertEqual(len(bar),1);self.assertEqual(len(desktop),1)
        self.assertFalse(desktop[0]['isSingleOnly'])
        self.assertEqual(desktop[0]['entry'],bar[0]['entry'])
        self.assertNotEqual(desktop[0]['id'],bar[0]['id'])
        self.assertEqual(desktop[0]['controls'],['play-pause','previous','next'])


if __name__=='__main__':unittest.main()

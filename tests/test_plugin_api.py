import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import adws_plugin as plugin
import adws_plugin_api as api
import adws_layout as layout
from adws_plugin_runner import execute


class PluginApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {'id':'org.Example_Host.Hello','name':'plugin.name','version':'1.0.0',
                         'entry':'main.py','renderer':'panel.text-v1'}

    def source(self, code='print(\'{"text":"Hello"}\')', manifest=None):
        source=self.root/'source';source.mkdir(exist_ok=True)
        (source/'plugin.json').write_text(json.dumps(manifest or self.manifest))
        (source/'main.py').write_text(code)
        return source

    def test_minimal_build_install_discover_run_remove(self):
        archive=plugin.build_package(self.source())
        env={'ADWS_PLUGIN_DIR':str(self.root/'plugins'),'ADWS_CACHE_DIR':str(self.root/'cache')}
        with patch.dict(os.environ,env),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(plugin.main(['install',str(archive)]),0)
            self.assertEqual(len(layout.scan_available_plugins()),1)
            self.assertEqual(plugin.main(['run',self.manifest['id']]),0)
            self.assertIn('Hello',output.getvalue())
            self.assertEqual(plugin.main(['remove',self.manifest['id']]),0)
            self.assertEqual(plugin.scan_packages(),[])

    def test_api_minimum_and_renderer_rejections(self):
        for changes in [{'renderer':'desktop.widget-v1'},{'adws':{'api':2}}, {'adws':{'api':True}},
                        {'adws':{'minVersion':'99.0'}},{'entry':'../main.py'},{'entry':'C:/main.py'},
                        {'adws':[]},{'defaults':{'width':-1}},{'settingsSchema':[{'key':'x','type':[]}]}]:
            self.assertTrue(plugin.validate_manifest({**self.manifest,**changes}),changes)

    def test_legacy_manifest_compatibility(self):
        old={**self.manifest,'api':'adws-plugin','apiVersion':1,'kind':'panel','language':'python','interfaces':['panel.json-v1']}
        del old['renderer']
        archive=plugin.build_package(self.source('import sys; assert "--output-json" in sys.argv; print(\'{"text":"legacy"}\')',old))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(execute(plugin.materialize(archive,self.root/'cache'),plugin.load_manifest(archive),{}),0)
        self.assertIn('legacy',out.getvalue())

    def test_localized_metadata_and_missing_key(self):
        source=self.source();(source/'locale').mkdir()
        for code,name in [('zh','你好'),('en','Hello')]:
            (source/'locale'/f'{code}.json').write_text(json.dumps({'plugin.name':name}))
        archive=plugin.build_package(source)
        for locale,name in [('zh_CN.UTF-8','你好'),('fr_FR.UTF-8','Hello')]:
            with patch.dict(os.environ,{'LC_ALL':locale,'LANGUAGE':''}):self.assertEqual(plugin.load_manifest(archive)['name'],name)
        self.manifest['name']='missing.key'
        archive=plugin.build_package(self.source())
        self.assertEqual(plugin.load_manifest(archive)['name'],'missing.key')

    def test_schema_boolean_fraction_and_invalid_defaults(self):
        schema=[{'key':'on','type':'boolean','default':True}, {'key':'fraction','type':'number','min':0,'max':1,'step':.1,'default':.5}]
        self.assertEqual(api.schema_errors(schema),[])
        self.assertEqual(api.settings({'settingsSchema':schema},{'fraction':.25}),{'on':True,'fraction':.25})
        for value in ['true',1,None]:
            with self.assertRaises(ValueError):api.settings({'settingsSchema':schema},{'on':value})
        self.assertTrue(api.schema_errors(schema+schema))

    def test_declared_panel_controls(self):
        self.assertEqual(api.public_errors({**self.manifest,
                                           'controls':['play-pause', 'previous', 'next']}), [])
        for controls in [['unknown'], ['next', 'next'], 'next']:
            self.assertIn('Invalid controls', api.public_errors({**self.manifest, 'controls': controls}))

    def test_zip_traversal_duplicates_and_missing_entry(self):
        for extra in ['../escape','/escape','foo/../../escape','C:/escape','foo\\bar','plugin.json']:
            archive=self.root/'bad.mplg'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('plugin.json',json.dumps(self.manifest));z.writestr('main.py','');z.writestr(extra,'{}')
            self.assertFalse(plugin.validate_package(archive)[0],extra)
        self.assertTrue(plugin.validate_manifest(self.manifest,{'plugin.json'}))

    def test_materialize_rebuilds_changed_archive_and_missing_entry(self):
        archive=plugin.build_package(self.source())
        dest=plugin.materialize(archive,self.root/'cache');(dest/'main.py').unlink()
        self.assertTrue((plugin.materialize(archive,self.root/'cache')/'main.py').is_file())
        original=archive.stat()
        archive=plugin.build_package(self.source('print(\'{"text":"Other"}\')'))
        os.utime(archive,ns=(original.st_atime_ns,original.st_mtime_ns))
        self.assertIn('Other',(plugin.materialize(archive,self.root/'cache')/'main.py').read_text())

    def test_runtime_failure_isolation_and_logs(self):
        for code in ['print("not JSON")','raise RuntimeError("bad")','import time; time.sleep(1)']:
            with contextlib.redirect_stdout(io.StringIO()) as out,contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(execute(self.source(code),api.normalize(self.manifest),{},timeout=.15),1)
                self.assertEqual(json.loads(out.getvalue())['class'],'error')
                self.assertIn('[plugin:org.Example_Host.Hello]',err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(execute(self.source(),api.normalize(self.manifest),{}),0)

    def test_legacy_unchanged_stream_does_not_timeout(self):
        manifest = api.normalize(self.manifest)
        del manifest['renderer']
        code = 'import time; print(\'{"text":"paused"}\', flush=True); time.sleep(.3); print(\'{"text":"resumed"}\', flush=True)'
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(execute(self.source(code),manifest,{},timeout=.15),0)
        self.assertIn('resumed',output.getvalue())

    def test_text_and_rows_layout_use_runner(self):
        for renderer in ['panel.text-v1','panel.rows-v1']:
            self.manifest['renderer']=renderer
            self.manifest['settingsSchema']=[{'key':'text','type':'string','default':''}]
            self.manifest['controls']=['play-pause', 'previous', 'next']
            archive=plugin.build_package(self.source())
            manifest=plugin.load_manifest(archive)
            available=[{'ok':True,'file':archive,'manifest':manifest}]
            state={'builtins':[],'plugins':[{'package':manifest['id'],'enabled':True,'width':0}],'options':{}}
            with patch.dict(os.environ,{'ADWS_CACHE_DIR':str(self.root/'cache')}):
                result=layout.render_waybar_config(state,available=available,base={})
            self.assertIn('adws_plugin_runner.py',json.dumps(result))
            module = next(key for key in result if key.startswith(('custom/adws-', 'cffi/adws-')))
            self.assertIn('--plugin', result[module].get('right_command', result[module].get('on-click-right', '')))
            self.assertIn(manifest['id'], result[module].get('right_command', result[module].get('on-click-right', '')))
            if renderer == 'panel.rows-v1':
                self.assertEqual(result[module]['width'], 0)
                self.assertFalse(result[module]['animations'])
                state['plugins'][0]['animations'] = True
                with patch.dict(os.environ,{'ADWS_CACHE_DIR':str(self.root/'cache')}):
                    animated = layout.render_waybar_config(state,available=available,base={})
                self.assertTrue(animated[module]['animations'])
                self.assertIn('--control play-pause', result[module]['left_command'])
                self.assertIn('--control previous', result[module]['previous_command'])
                self.assertIn('--control next', result[module]['next_command'])
            else:
                self.assertFalse(result[module]['tooltip'])

    def test_lyrics_id_migration_preserves_settings(self):
        path=self.root/'layout.json'
        path.write_text(json.dumps({'plugins':[{'package':'org.adws.neteaselyrics','enabled':True,'slot':'center','settings':{'offset_ms':200}}]}))
        item=layout.load_layout(path)['plugins'][0]
        self.assertEqual(item['package'],'org.AkiACG_Community.NCMLyricsBar')
        self.assertEqual(item['settings'],{'offset_ms':200});self.assertTrue(item['enabled'])

    def test_reference_and_sample_build(self):
        for source in ['plugins/sample','plugins/netease-lyrics']:
            archive=plugin.build_package(ROOT/source,self.root/(Path(source).name+'.mplg'))
            self.assertTrue(plugin.validate_package(archive)[0])


if __name__ == '__main__':unittest.main()

import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_setup as setup


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / 'project/component'
        self.cwd.mkdir(parents=True)
        self.env = {'HOME': str(self.root / 'home'), 'CARGO_HOME': str(self.root / 'cargo')}
        self.cwd_patch = patch.object(setup.Path, 'cwd', return_value=self.cwd)
        self.cwd_patch.start()
        self.addCleanup(self.cwd_patch.stop)

    def config(self, contents, folder=None, name='config.toml'):
        path = (folder or Path(self.env['CARGO_HOME'])) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        return path

    def test_non_chinese_never_prompts(self):
        with patch('adws_i18n.chinese',return_value=False), patch.object(setup,'confirm') as ask:
            self.assertEqual(setup.choose_build_mirror(self.env)['ADWS_BUILD_MIRROR'],'0')
            ask.assert_not_called()

    def test_chinese_prompts_once(self):
        with patch('adws_i18n.chinese',return_value=True), patch.object(setup,'confirm',return_value=True) as ask:
            env=setup.choose_build_mirror(self.env)
            self.assertEqual(env['ADWS_BUILD_MIRROR'],'1')
            self.assertEqual(setup.choose_build_mirror(env),env)
            ask.assert_called_once()
            self.assertIn('source.crates-io.replace-with="adws-rsproxy"',setup.cargo_build_command(env))

    def test_decline_uses_default(self):
        with patch('adws_i18n.chinese',return_value=True), patch.object(setup,'confirm',return_value=False):
            self.assertEqual(setup.cargo_build_command(setup.choose_build_mirror(self.env)),['cargo','build','--release','--locked'])

    def test_existing_rsproxy_not_registered_twice(self):
        contents = '[source.crates-io]\nreplace-with="rsproxy"\n[source.rsproxy]\nregistry="sparse+https://rsproxy.cn/index/"\n'
        path = self.config(contents)
        with patch.object(setup,'confirm') as ask:
            env = setup.choose_build_mirror({**self.env,'ADWS_BUILD_MIRROR':'1'})
            self.assertEqual(env['ADWS_BUILD_MIRROR'],'0')
            self.assertNotIn('--config', setup.cargo_build_command(env))
            ask.assert_not_called()
        self.assertEqual(path.read_text(), contents)

    def test_ancestor_vendor_and_component_recheck(self):
        self.config('[source.crates-io]\nreplace-with="vendored"\n[source.vendored]\ndirectory="vendor"', self.cwd.parent/'.cargo')
        self.assertNotIn('--config', setup.cargo_build_command({**self.env,'ADWS_BUILD_MIRROR':'1'},self.cwd))

    def test_legacy_config_wins(self):
        self.config('this is invalid TOML', name='config.toml')
        self.config('[source.rsproxy]\nregistry="sparse+https://rsproxy.cn/index/"', name='config')
        self.assertTrue(setup.cargo_source_configuration(self.env))

    def test_malformed_config_reports_path(self):
        path = self.config('this is invalid TOML')
        with self.assertRaisesRegex(RuntimeError, str(path)):
            setup.choose_build_mirror(self.env)

    def test_custom_registry_environment(self):
        env = {**self.env,'CARGO_REGISTRIES_CRATES_IO_INDEX':'https://mirror.invalid/index','ADWS_BUILD_MIRROR':'1'}
        self.assertNotIn('--config',setup.cargo_build_command(env))

    def test_unrelated_build_options_allow_mirror(self):
        self.config('[build]\njobs=2\n')
        env = {**self.env,'ADWS_BUILD_MIRROR':'1','RUSTUP_DIST_SERVER':'https://rsproxy.cn'}
        self.assertIn('--config',setup.cargo_build_command(env))

    def test_unused_same_url_registry_also_preserved(self):
        self.config('[registries.my-mirror]\nindex="sparse+https://rsproxy.cn/index/"')
        self.assertNotIn('--config',setup.cargo_build_command({**self.env,'ADWS_BUILD_MIRROR':'1'}))

if __name__ == '__main__':
    unittest.main()

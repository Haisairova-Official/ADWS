import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_runtime_dependencies as deps
import adws_setup as setup

class RuntimeDependencyTests(unittest.TestCase):
    def probe(self, payload='[]', missing=(), returncode=0):
        with patch.object(deps.shutil,'which',side_effect=lambda name:None if name in missing else '/usr/bin/'+name), patch.object(deps.subprocess,'run',return_value=subprocess.CompletedProcess([],returncode,payload,'GstApp unavailable' if returncode else '')):
            return deps.missing_dependencies()

    def test_complete_runtime_needs_nothing(self):
        self.assertEqual(self.probe(),{})

    def test_missing_gstreamer_elements_not_just_imports(self):
        self.assertEqual(self.probe('["pipewiresrc","pngenc"]'),{'preview':['pipewiresrc','pngenc']})
        self.assertIn('GstApp unavailable',str(self.probe(returncode=1)))

    def test_capture_and_session_manager_mapping(self):
        missing=self.probe(missing=('grim','slurp','wl-copy','wireplumber','pipewire-media-session'))
        self.assertEqual(missing['capture'],['grim','slurp','wl-copy'])
        self.assertEqual(deps.install_groups(missing),['capture','preview','preview-session'])
        self.assertEqual(self.probe(missing=('wireplumber',)),{})

    def test_timeout_reported(self):
        with patch.object(deps.shutil,'which',return_value='/bin/tool'),patch.object(deps.subprocess,'run',side_effect=subprocess.TimeoutExpired('probe',15)):
            self.assertIn('preview',deps.missing_dependencies())

    def test_each_distribution_installs_capture_and_preview_runtime(self):
        expected={'apt-get':'gstreamer1.0-pipewire','pacman':'gst-plugin-pipewire','dnf':'pipewire-gstreamer'}
        for manager,plugin in expected.items():
            with self.subTest(manager=manager),patch.object(setup.shutil,'which',side_effect=lambda name:'/usr/bin/'+name if name==manager else None),patch.object(setup,'confirm',return_value=True),patch.object(setup.os,'geteuid',return_value=0),patch.object(setup.subprocess,'run') as run:
                setup.install_packages(groups=['capture','preview'])
                command=run.call_args.args[0]
                for package in ('grim','slurp','wl-clipboard','pipewire',plugin):self.assertIn(package,command)
                self.assertNotIn('wireplumber',command,'Do not replace an existing session manager')
                self.assertFalse(any('pipewire-pulse' in name for name in command))

    def test_setup_repairs_features_before_native_prebuilt_path(self):
        with patch('adws_niri_install.ensure_niri'),patch.object(setup,'resolve_waybar',return_value='/bin/waybar'),patch.object(setup,'dependency_errors',side_effect=[['missing preview'],[]]) as check,patch('adws_runtime_dependencies.missing_dependencies',return_value={'preview':['pngenc']}),patch.object(setup.shutil,'which',return_value='/bin/tool'),patch.object(setup,'install_packages') as install,patch('adws_fonts.ensure_fonts',side_effect=RuntimeError('reached fonts')),patch('adws_prebuilt.install') as prebuilt:
            with self.assertRaisesRegex(RuntimeError,'reached fonts'):setup.prepare()
            install.assert_called_once_with([],['preview'])
            self.assertEqual(check.call_count,2)
            prebuilt.assert_not_called()

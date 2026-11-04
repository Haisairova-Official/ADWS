import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_display_profile as profile
from adws_monitor_identity import assign

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'config.kdl'
        self.output=assign([dict(name='DP-1',make='V',model='4K',serial='123',mode='3840x2160@60.000',scale=1.5,x=0,y=0,transform=0)])[0]

    def test_preserves_unrelated_settings_and_outputs(self):
        self.root.write_text('input { keyboard { xkb { layout "us"; }; }; }\noutput "DP-1" { scale 1; variable-refresh-rate; }\noutput "HDMI-A-1" { scale 2; }\n')
        files,nodes=profile.config_tree(self.root)
        text=profile.compose(files,nodes,[self.output],self.root)[self.root]
        self.assertIn('variable-refresh-rate',text)
        self.assertIn('output "HDMI-A-1" { scale 2; }',text)
        self.assertIn('output "V 4K 123"',text)
        self.assertNotIn('output "DP-1"',text)
        self.assertIn('layout "us"',text)

    def test_include_nodes_migrated_without_touching_keyboard(self):
        child=self.root.parent/'other.kdl'
        child.write_text('output "DP-1" { scale 1; }\nbinds { Mod+Return { spawn "kitty"; }; }\n')
        self.root.write_text('include "other.kdl"\n')
        files,nodes=profile.config_tree(self.root)
        changed=profile.compose(files,nodes,[self.output],self.root)
        self.assertIn('spawn "kitty"',changed[child])
        self.assertNotIn('output "DP-1"',changed[child])
        self.assertIn('include "other.kdl"',changed[self.root])

    def test_validation_failure_never_writes(self):
        original='output "DP-1" { scale 1; }\n';self.root.write_text(original)
        with patch.object(profile,'validate_bundle',side_effect=ValueError('bad')):
            with self.assertRaises(ValueError):profile.persist([self.output],self.root)
        self.assertEqual(self.root.read_text(),original)

    def test_persist_is_idempotent_and_retains_disconnected_profile(self):
        self.root.write_text('')
        with patch.object(profile,'validate_bundle'):
            profile.persist([self.output],self.root)
            original=self.root.read_text()
            profile.persist([self.output],self.root)
            self.assertEqual(original,self.root.read_text())
            other=dict(self.output,name='DP-2',selector='Other monitor 456')
            profile.persist([other],self.root)
        self.assertIn('output "V 4K 123"',self.root.read_text())
        self.assertIn('output "Other monitor 456"',self.root.read_text())

    def test_independent_guard_restores_on_gui_pipe_close(self):
        import json
        log=self.root.parent/'calls.jsonl'
        binary=self.root.parent/'niri'
        binary.write_text('#!'+sys.executable+'\nimport sys,json\nwith open('+repr(str(log))+',"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n')
        binary.chmod(0o755)
        with patch.dict(os.environ,{'PATH':str(binary.parent)+os.pathsep+os.environ.get('PATH','')}):
            guard=profile.PreviewGuard('niri',[self.output])
            guard.process.stdin.close()  # GUI crash: no keep message.
            self.assertEqual(guard.process.wait(timeout=5),0)
            self.assertEqual(len(log.read_text().splitlines()),4)
            log.unlink()
            guard=profile.PreviewGuard('niri',[self.output]);guard.finish(True)
            self.assertEqual(guard.process.wait(timeout=5),0)
            self.assertFalse(log.exists())

if __name__=='__main__':unittest.main()

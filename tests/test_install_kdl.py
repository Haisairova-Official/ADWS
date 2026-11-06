from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_install_kdl import include, spawn
from adws_install_session_config import niri_environment
import adws_install_startup as startup

class IncludeTests(unittest.TestCase):
    def test_spawn_literals_allow_terminators_comments_and_escaped_quotes(self):
        self.assertEqual(spawn('spawn-at-startup "ibus-daemon"; // keep IBus'),('spawn-at-startup',['ibus-daemon']))
        self.assertEqual(spawn('spawn-sh-at-startup "env XMODIFIERS=@im=ibus ibus-daemon";'),('spawn-sh-at-startup',['env XMODIFIERS=@im=ibus ibus-daemon']))
        for text in ('spawn-at-startup "one"; spawn-at-startup "two"', 'spawn-at-startup bare', 'spawn-at-startup "a" key="b"'):
            with self.assertRaises(ValueError):spawn(text)

    def test_optional_include_both_attribute_orders_and_comments(self):
        for text in ['include optional=true "my rule.kdl"','include "my rule.kdl" optional=true; // comment','include\toptional=true "my rule.kdl"']:
            self.assertEqual(include(text),('my rule.kdl',True))
        self.assertEqual(include('include "rule.kdl" optional=false'),('rule.kdl',False))
        self.assertIsNone(include('// include "disabled.kdl"'))
        with self.assertRaises(ValueError):include('include optional=maybe "x.kdl"')

    def test_optional_child_is_audited_when_present_and_ignored_only_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.kdl'
            config.write_text('include optional=true "child.kdl"\n')
            values,unknown,_=niri_environment(config)
            self.assertFalse(unknown)
            opts={'enabled_units':[],'unit_dirs':[],'autostart_dirs':[]}
            self.assertFalse(startup.audit(root,config,**opts)['unknown'])
            (root/'child.kdl').write_text('environment { QT_IM_MODULE "ibus"; }\nspawn-at-startup "fcitx5"\n')
            self.assertEqual(niri_environment(config)[0]['QT_IM_MODULE'],'ibus')
            self.assertEqual(len(startup.audit(root,config,**opts)['owners']['input-method']),1)
            config.write_text('include "required.kdl"\n')
            self.assertTrue(niri_environment(config)[1])
            self.assertTrue(startup.audit(root,config,**opts)['unknown'])

if __name__=='__main__':unittest.main()

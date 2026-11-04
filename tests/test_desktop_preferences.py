import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_desktop_preferences as preferences

class PreferencesTests(unittest.TestCase):
    def test_persistence_and_disconnect_do_not_lose_selection(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'XDG_CONFIG_HOME':folder}):
            monitor=SimpleNamespace(get_geometry=lambda:SimpleNamespace(x=0,y=0))
            first=SimpleNamespace(monitor_key='first',connector_key='DP-1',monitor=monitor)
            second=SimpleNamespace(monitor_key='second',connector_key='DP-2',monitor=monitor)
            preferences.save('second','DP-2','Second display')
            self.assertIs(preferences.choose([first,second],monitor),second)
            self.assertIs(preferences.choose([first],monitor),first)
            self.assertEqual(preferences.load()['default_monitor'],'second')
            second.connector_key='HDMI-A-1'
            self.assertIs(preferences.choose([first,second],monitor),second)
            self.assertEqual(preferences.load()['label'],'Second display')

    def test_bad_config_falls_back_and_other_fields_survive(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'XDG_CONFIG_HOME':folder}):
            preferences.path().parent.mkdir()
            preferences.path().write_text('{')
            self.assertEqual(preferences.load()['default_monitor'],'primary')
            preferences.path().write_text('{"default_monitor":"primary","other":42}')
            preferences.save('screen')
            self.assertEqual(preferences.load()['other'],42)

if __name__=='__main__':unittest.main()

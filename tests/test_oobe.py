import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_oobe as oobe


class SetupTests(unittest.TestCase):
    def test_first_run_and_existing_configuration(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CONFIG_HOME': temp}):
            self.assertTrue(oobe.needed())
            oobe.write_json(oobe.folder()/'setup.json', {'completed': True})
            self.assertFalse(oobe.needed())
            (oobe.folder()/'setup.json').unlink()
            oobe.write_json(oobe.folder()/'taskbar-layout.json', {'options': {}})
            self.assertFalse(oobe.needed())

    def test_no_display_never_launches(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(oobe.subprocess, 'Popen') as spawn:
            oobe.launch()
            spawn.assert_not_called()

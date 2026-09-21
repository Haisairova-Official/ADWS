import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import adws_migrate as migration


class MigrationTests(unittest.TestCase):
    def test_moves_paths_rewrites_configs_and_retires_old_plugins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, state, data, cache = (root / name for name in ("config", "state", "data", "cache"))
            old_layout = config / "mnws/taskbar-layout.json"
            old_layout.parent.mkdir(parents=True)
            old_layout.write_text('{"module":"custom/mnws-test"}')
            waybar = config / "waybar"
            waybar.mkdir()
            modules = waybar / "modules.jsonc"
            modules.write_text('"custom/mnws-test" // MNWS')
            legacy_plugin = data / "mnws/plugins/old.mplg"
            legacy_plugin.parent.mkdir(parents=True)
            legacy_plugin.write_bytes(b"legacy")
            old_library = root / "lib/libmnws_panel.so"
            old_library.parent.mkdir()
            old_library.write_bytes(b"old")
            old_command = root / "bin/mnws"
            old_command.parent.mkdir()
            old_command.symlink_to(root / "MNWS/mnws")
            official = root / "source/plugins/org.AkiACG_Community.NCMLyricsBar_1.1.0.mplg"
            official.parent.mkdir(parents=True)
            official.write_bytes(b"new")

            messages = migration.migrate(config, state, data, cache, old_command.parent, old_library.parent, root / "source")

            self.assertTrue((config / "adws/taskbar-layout.json").is_file())
            self.assertFalse((config / "mnws").exists())
            self.assertIn("adws", modules.read_text())
            self.assertTrue((waybar / "modules.jsonc.adws-migration.bak").is_file())
            self.assertTrue((data / "adws/legacy-mnws-plugins/old.mplg").is_file())
            self.assertTrue((data / "adws/plugins" / official.name).is_file())
            self.assertFalse(old_command.exists() or old_command.is_symlink())
            self.assertFalse(old_library.exists())
            self.assertTrue(messages)

    def test_repeat_install_preserves_adws_plugins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "data/adws/plugins/user.mplg"
            package.parent.mkdir(parents=True)
            package.write_bytes(b"user package")
            for _ in range(2):
                migration.migrate(*(root / name for name in ("config", "state", "data", "cache", "bin", "lib")), root / "source")
            self.assertEqual(package.read_bytes(), b"user package")
            self.assertFalse((root / "data/adws/legacy-mnws-plugins").exists())

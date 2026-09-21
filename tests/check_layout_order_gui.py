"""Regression: open/save preserves a mixed builtin/plugin order."""
import copy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import mnws_layout_gui as gui
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

manifest = json.loads((ROOT / "plugins/netease-lyrics/plugin.json").read_text())
ids = ["test.zfirst", "test.alast", "test.center"]
packages = []
for package_id in ids:
    item = copy.deepcopy(manifest)
    item["id"] = package_id
    packages.append({"ok": True, "manifest": item, "file": Path("/tmp") / (package_id + ".mplg")})
gui.scan_available_plugins = lambda: packages

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "layout.json"
    data = {
        "builtins": [
            {"id": "start", "slot": "left", "order": 0, "enabled": True},
            {"id": "windows", "slot": "left", "order": 1, "enabled": True},
            {"id": "workspaces", "slot": "right", "order": 1, "enabled": True},
            {"id": "clock", "slot": "right", "order": 2, "enabled": True},
        ],
        "plugins": [
            {"package": ids[0], "slot": "right", "order": 0, "enabled": True, "settings": {"primary_color": "#123456"}},
            {"package": ids[1], "slot": "right", "order": 3, "enabled": True},
            {"package": ids[2], "slot": "center", "order": 0, "enabled": True},
        ],
    }
    missing = {"package": "test.temporarily-missing", "enabled": True, "slot": "right", "order": 9, "settings": {"keep": "me"}}
    data["plugins"].append(missing)
    path.write_text(json.dumps(data))
    app = gui.LayoutWindow(str(path))
    expected = ["start", "windows", ids[2], ids[0], "workspaces", "clock", ids[1]]
    stable = None
    for _ in range(5):
        assert [row["key"] for row in app.rows] == expected
        saved = app.collect_layout()
        assert missing in saved["plugins"], "Unavailable plugin settings were discarded"
        if stable is not None:
            assert saved == stable
        stable = saved
        assert next(item for item in saved["plugins"] if item["package"] == ids[0])["settings"] == {"primary_color": "#123456"}
        path.write_text(json.dumps(saved))
        app.reload()
    row = next(row for row in app.rows if row["key"] == ids[1])
    app.move_row(row, -1)
    assert [row["key"] for row in app.rows][-2:] == [ids[1], "clock"]
    row["widgets"]["slot"].set_active_id("center")
    assert [r["key"] for r in app.rows if r["slot"] == "center"] == [ids[2], ids[1]]
    app.move_row(row, -1)
    assert [r["key"] for r in app.rows if r["slot"] == "center"] == [ids[1], ids[2]]
    expected = [r["key"] for r in app.rows]
    path.write_text(json.dumps(app.collect_layout()))
    app.reload()
    assert [r["key"] for r in app.rows] == expected
    # Launcher selection survives saving/reopening, retaining the custom draft.
    app.launcher_mode.set_active_id("custom")
    app.launcher_command.set_text('wofi --show drun --style "my theme.css"')
    custom = app.collect_layout()["options"]["start_launcher_command"]
    for mode, command in [("fuzzel", "fuzzel"), ("rofi", "rofi -show drun"), ("custom", custom)]:
        app.launcher_mode.set_active_id(mode)
        saved = app.collect_layout()
        assert saved["options"]["start_launcher_command"] == command
        path.write_text(json.dumps(saved))
        app.reload()
        assert app.launcher_mode.get_active_id() == mode
        assert app.launcher_command.get_text() == custom
        assert app.launcher_command.get_sensitive() == (mode == "custom")
        assert app.rofi_theme_button.get_visible() == (mode == "rofi")
    app.launcher_mode.set_active_id("rofi")
    app.on_rofi_theme()
    assert gui.rofi_theme_command() == "rofi -show drun -theme-str 'mainbox { background-image: none; }'"
    path.write_text(json.dumps(app.collect_layout()))
    app.reload()
    assert app.launcher_mode.get_active_id() == "rofi"
    assert app.collect_layout()["options"]["start_launcher_command"] == gui.rofi_theme_command()
    app.launcher_mode.set_active_id("custom")
    app.launcher_command.set_text(" ")
    try:
        app.collect_layout()
    except ValueError:
        pass
    else:
        raise AssertionError("Empty custom launcher must not be saved")
    from gi.repository import GdkPixbuf
    normal = Path(directory) / "normal.png"
    hover = Path(directory) / "hover.png"
    for file, width in [(normal, 80), (hover, 81)]:
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, 20)
        pixbuf.fill(0xff0000ff)
        pixbuf.savev(str(file), "png", [], [])
    app.launcher_mode.set_active_id("rofi")
    app.start_mode.set_active_id("image")
    app.start_images["start_image"].set_text(str(normal))
    app.start_images["start_hover_image"].set_text(str(hover))
    assert app.image_error.get_text()
    try:
        app.collect_layout()
    except ValueError:
        pass
    else:
        raise AssertionError("Mismatched dimensions must block save")
    hover.write_bytes(normal.read_bytes())
    app.check_start_images()
    assert not app.image_error.get_text()
    saved = app.collect_layout()
    rendered = gui.mnws_layout.render_waybar_config(saved, available=[], base={})
    assert 'cffi/start-button' in rendered['modules-left']
    assert rendered['cffi/start-button']['start_hover_image'] == str(hover)
    path.write_text(json.dumps(saved))
    app.reload()
    assert app.start_mode.get_active_id() == 'image'
    app.start_images['start_hover_image'].set_text('')
    assert app.collect_layout()['options']['start_hover_image'] == ''
    app.window.disconnect_by_func(Gtk.main_quit)
    app.window.destroy()
print("Mixed order survived five open/save cycles, cross-type moves, and section changes.")

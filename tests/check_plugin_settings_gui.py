"""Run under Xvfb; exercise the real settings and layout widgets without saving."""
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adws_layout_gui as gui
from adws_plugin_settings import SettingsDialog, validate_settings
from gi.repository import Gtk


def settle():
    for _ in range(30):
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(.005)


def capture(window, path):
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, window.get_allocated_width(), window.get_allocated_height())
    window.draw(cairo.Context(surface))
    surface.write_to_png(path)


with tempfile.TemporaryDirectory() as temp:
    manifest = json.loads((ROOT / "plugins/netease-lyrics/plugin.json").read_text())
    manifest["name"] = "一个特别特别长的歌词插件名称" * 12
    gui.scan_available_plugins = lambda: [{"ok": True, "manifest": manifest, "file": ROOT / "plugins/very-long-package-name.mplg"}]
    path = Path(temp) / "layout.json"
    settings = {"interval": 0, "font_family": "Sans", "primary_color": "#ff0000"}
    path.write_text(json.dumps({"builtins": [], "plugins": [{"package": manifest["id"], "enabled": True, "settings": settings}]}))
    app = gui.LayoutWindow(str(path))
    settle()
    row = next(row for row in app.rows if row["kind"] == "plugin")
    for widget in row["box"].get_children():
        if isinstance(widget, Gtk.Button):
            start = widget.translate_coordinates(app.window, 0, 0)[0]
            assert start >= 0 and start + widget.get_allocated_width() <= app.window.get_allocated_width(), widget.get_label()
    labels = row["box"].get_children()[1].get_children()
    assert all(label.get_layout().is_ellipsized() for label in labels)
    assert app.collect_layout()["plugins"][0]["settings"] == settings
    assert app.collect_layout()["plugins"][0]["animations"] is False
    row["animations"] = True
    assert app.collect_layout()["plugins"][0]["animations"] is True
    capture(app.window, "/tmp/adws-layout-settings-preview.png")
    dialog = SettingsDialog(app.window, "网易云歌词", manifest["settingsSchema"], settings, animations=False)
    dialog.dialog.show_all()
    settle()
    values = dialog.collect()
    assert dialog.animations is False
    dialog.animation_toggle.set_active(True)
    assert "animations" not in dialog.collect()  # Host setting must not leak into plugin settings.
    assert dialog.animations is True
    assert values["font_family"] == "Sans"
    assert values["primary_color"].startswith("rgb")
    assert values["interval"] == 0
    assert dialog.dialog.get_transient_for() == app.window
    capture(dialog.dialog, "/tmp/adws-plugin-settings-preview.png")
    validate_settings({"api_mode": "custom", "api_url": "https://example.test/lyrics?title={title}"})
    try:
        validate_settings({"api_mode": "custom", "api_url": "https://example.test/{unknown}"})
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid template accepted")
    dialog.dialog.destroy()
    boolean = SettingsDialog(app.window, 'API types', [
        {'key':'enabled','type':'boolean','default':True},
        {'key':'fraction','type':'number','min':0,'max':1,'step':.1,'default':.5}], {})
    boolean.dialog.show_all()
    settle()
    assert boolean.collect() == {'enabled': True, 'fraction': .5}
    boolean.controls['enabled'][1].set_active(False)
    assert boolean.collect()['enabled'] is False
    boolean.dialog.destroy()
    app.window.disconnect_by_func(Gtk.main_quit)
    app.window.destroy()
    print("Settings persistence, controls, long-name ellipsis and button visibility passed.")

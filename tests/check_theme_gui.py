"""Run under Xvfb; theme edits only touch a temporary configuration directory."""
import os
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from adws_theme import start, _watchers

def settle():
    end = time.monotonic() + .7
    while time.monotonic() < end:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)

with tempfile.TemporaryDirectory() as tmp:
    os.environ['XDG_CONFIG_HOME'] = tmp
    folder = Path(tmp) / 'gtk-3.0'; folder.mkdir()
    css = folder / 'gtk.css'
    css.write_text('@import "colors.css"; button {background-image:none; background-color:@accent; transition:none;}')
    palette = folder / 'colors.css'
    palette.write_text('@define-color accent #ff0000;')
    Gtk.init([])
    start(); start()
    assert len(_watchers) == 1
    window = Gtk.Window(); button = Gtk.Button(label='live'); window.add(button); window.show_all()
    settle()
    context = button.get_style_context()
    assert context.get_background_color(Gtk.StateFlags.NORMAL).red > .9
    replacement = folder / 'new.css'; replacement.write_text('@define-color accent #0000ff;'); replacement.replace(palette)
    settle()
    assert context.get_background_color(Gtk.StateFlags.NORMAL).blue > .9
    palette.write_text('invalid CSS {')
    settle()
    assert context.get_background_color(Gtk.StateFlags.NORMAL).blue > .9
    palette.write_text('@define-color accent #00ff00;')
    settle()
    assert context.get_background_color(Gtk.StateFlags.NORMAL).green > .9
    window.destroy()
    # Menus already created before a palette change must update too.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/niri-desktop-layer'))
    from desktop_layer.app import apply_menu_palette
    from types import SimpleNamespace
    bar = Path(tmp) / 'waybar'; bar.mkdir()
    colors = bar / 'colors.css'
    colors.write_text('@define-color on_surface #ff0000;')
    menu = Gtk.Menu(); item = Gtk.MenuItem(label='live menu'); menu.append(item)
    apply_menu_palette(menu, SimpleNamespace(font_family='Sans'))
    menu.show_all(); settle()
    assert item.get_style_context().get_color(Gtk.StateFlags.NORMAL).red > .9
    colors.write_text('@define-color on_surface #0000ff;'); settle()
    assert item.get_style_context().get_color(Gtk.StateFlags.NORMAL).blue > .9
    menu.destroy()
    assert menu._adws_palette_watch.source == 0
    for watcher in _watchers: watcher.close()
print('Live theme update, atomic replacement, invalid-write recovery and singleton checks passed.')

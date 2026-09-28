"""Run under an isolated Xvfb display with a temporary HOME."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_oobe as oobe
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk

def walk(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children(): yield from walk(child)

with tempfile.TemporaryDirectory(prefix='adws-setup-gui-') as temp:
    os.environ.update(HOME=temp, XDG_CONFIG_HOME=temp+'/config', XDG_STATE_HOME=temp+'/state', XDG_DATA_HOME=temp+'/data')
    failures=[]
    failure_mode=os.environ.get('ADWS_SETUP_FAILURE','')
    error_verified=[]
    def click_through():
        try:
            window=next(w for w in Gtk.Window.list_toplevels() if w.is_visible())
            if os.environ.get('ADWS_SETUP_SCREENSHOT'):
                Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, window.get_allocated_width(), window.get_allocated_height()).savev(os.environ['ADWS_SETUP_SCREENSHOT'], 'png', [], [])
            buttons=[w for w in walk(window) if isinstance(w, Gtk.Button)]
            next_button=next(b for b in buttons if b.get_label()==oobe._tr('下一步'))
            for _ in range(5): next_button.clicked()
            assert next_button.get_label()==oobe._tr('完成设置')
            next_button.clicked()
            if failure_mode:
                def error_returned():
                    try:
                        if not next_button.is_sensitive():return True
                        labels=[w.get_text() for w in walk(window) if isinstance(w,Gtk.Label)]
                        assert any('injected setup failure' in text for text in labels),labels
                        error_verified.append(True)
                        window.destroy()
                    except Exception as exc:
                        failures.append(exc);Gtk.main_quit()
                    return False
                GLib.timeout_add(30,error_returned)
        except Exception as e:
            failures.append(e);Gtk.main_quit()
        return False
    def timeout():
        failures.append(RuntimeError('Wizard did not complete'));Gtk.main_quit();return False
    GLib.timeout_add(200, click_through)
    timer=GLib.timeout_add_seconds(10,timeout)
    with ExitStack() as patches:
        patches.enter_context(patch('adws_runtime.pids',return_value=[123] if failure_mode=='restart' else []))
        patches.enter_context(patch('adws_wallpaper.installed',return_value=[]))
        patches.enter_context(patch('adws_wallpaper.running',return_value={}))
        apply_wallpaper=patches.enter_context(patch('adws_wallpaper.apply'))
        if failure_mode=='restart':
            patches.enter_context(patch('adws_layout.restart_taskbar',side_effect=OSError('injected setup failure')))
        elif failure_mode:
            patches.enter_context(patch.object(oobe,'save_settings',side_effect=RuntimeError('injected setup failure')))
        oobe.run()
        apply_wallpaper.assert_not_called()
    GLib.source_remove(timer)
    if failures:raise failures[0]
    if failure_mode:
        assert error_verified,'Wizard did not return to an interactive state'
        print('OOBE error display and retry buttons verified:',failure_mode)
    if failure_mode in ('','restart'):
        assert (oobe.folder()/'taskbar-layout.json').is_file()
        assert not oobe.needed()
        print('OOBE pages and saved settings verified.')

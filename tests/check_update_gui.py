"""Exercise asynchronous update UI and capture switches without changing live state."""
import importlib.util
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
spec = importlib.util.spec_from_file_location('mnws_config', ROOT/'tools/mnws-config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
Gtk = config.Gtk

def settle(until=None):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        if until is not None and until(): return
        time.sleep(.01)
    if until is not None: raise AssertionError('GUI update timed out')

with patch.object(config.ConfigWindow, 'refresh_statuses'), patch.object(config, 'desktop_autostart_enabled', return_value=False):
    window = config.ConfigWindow(tab='about')
    window.notebook.set_current_page(2)
    ready = threading.Event()
    def slow_check():
        ready.wait(2)
        return {'available':False,'text':'No updates found.','url':None}
    with patch('mnws_update.check_update', side_effect=slow_check):
        window.check_updates()
        assert not window.update_button.get_sensitive()
        ticks = []
        config.GLib.idle_add(lambda: ticks.append(True) and False)
        settle(lambda: bool(ticks))
        ready.set()
        settle(lambda: window.update_button.get_sensitive())
        assert window.update_result.get_text() == 'No updates found.'
        assert not window.update_link.get_visible()
    with patch('mnws_update.check_update', return_value={'available':True,'text':'New version available','url':'https://github.com/Haisairova-Official/MNWS/releases/tag/v1.3'}):
        window.check_updates()
        settle(lambda: window.update_button.get_sensitive())
        assert window.update_link.get_visible()
    with patch('mnws_update.check_update', side_effect=RuntimeError('Network unavailable')):
        window.check_updates()
        settle(lambda: window.update_button.get_sensitive())
        assert window.update_result.get_text() == 'Network unavailable'
        assert not window.update_link.get_visible()
    window.notebook.set_current_page(1)
    window.resize(800, 760)
    settle(lambda: window.get_allocated_width() >= 800)
    for switch in (window.desktop_switch, window.taskbar_switch):
        assert switch.get_allocated_width() <= switch.get_preferred_width()[1]
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, window.get_allocated_width(), window.get_allocated_height())
    window.draw(cairo.Context(surface))
    language = 'zh' if os.environ.get('LANGUAGE','').startswith('zh') else 'en'
    surface.write_to_png(f'/tmp/mnws-components-{language}.png')
    window.hide()
print('Update UI remained responsive; results/errors recovered correctly and switches retained natural width.')

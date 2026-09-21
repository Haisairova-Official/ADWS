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
    def slow_check(preview=False):
        assert not preview
        ready.wait(2)
        return {'available':False,'text':'No updates found.','url':None}
    with patch('mnws_update.check_update', side_effect=slow_check):
        window.check_updates()
        assert not window.update_button.get_sensitive()
        assert not window.update_preview.get_sensitive()
        ticks = []
        config.GLib.idle_add(lambda: ticks.append(True) and False)
        settle(lambda: bool(ticks))
        ready.set()
        settle(lambda: window.update_button.get_sensitive())
        assert window.update_result.get_text() == 'No updates found.'
        assert not window.update_link.get_visible()
    window.update_preview.set_active(True)
    with patch('mnws_update.check_update', return_value={'available':True,'text':'New version available','url':'https://github.com/Haisairova-Official/MNWS/releases/tag/v1.3'}) as check, patch.object(window, 'confirm_update', return_value=False):
        window.check_updates()
        settle(lambda: window.update_button.get_sensitive())
        assert window.update_link.get_visible()
        assert window.update_preview.get_sensitive()
        check.assert_called_once_with(preview=True)
    result = {'available':True,'text':'New version available','url':'https://github.com/Haisairova-Official/MNWS/releases/tag/v1.3'}
    with patch.object(Gtk.MessageDialog, 'run', return_value=Gtk.ResponseType.CANCEL):
        assert not window.confirm_update(result)
        assert window.update_result.get_text() == config._tr('已取消。')
    started = threading.Event()
    release = threading.Event()
    def slow_install(selected, progress):
        assert selected == result
        progress('Downloading test update')
        started.set()
        release.wait(2)
        return 'Update installed; backup saved'
    with patch('mnws_update.check_update', return_value=result), patch.object(Gtk.MessageDialog, 'run', return_value=Gtk.ResponseType.OK), patch('mnws_update.install_update', side_effect=slow_install) as install:
        window.check_updates()
        settle(started.is_set)
        assert not window.update_button.get_sensitive()
        assert not window.update_preview.get_sensitive()
        ticks = []
        config.GLib.idle_add(lambda: ticks.append(True) and False)
        settle(lambda: bool(ticks))
        release.set()
        settle(lambda: window.update_button.get_sensitive())
        install.assert_called_once()
        assert window.update_result.get_text() == 'Update installed; backup saved'
    with patch('mnws_update.install_update', side_effect=RuntimeError('Install failed; old version retained')):
        window.install_update(result)
        settle(lambda: window.update_button.get_sensitive())
        assert window.update_result.get_text() == 'Install failed; old version retained'
        assert window.update_preview.get_sensitive()
    with patch('mnws_update.check_update', side_effect=RuntimeError('Network unavailable')):
        window.check_updates()
        settle(lambda: window.update_button.get_sensitive())
        assert window.update_result.get_text() == 'Network unavailable'
        assert not window.update_link.get_visible()
    settle()
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, window.get_allocated_width(), window.get_allocated_height())
    window.draw(cairo.Context(surface))
    surface.write_to_png('/tmp/mnws-update-preview.png')
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

"""Sidebar/control-center brightness cards probe on open, never on timer ticks."""
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from adws_sidebar_widgets import LevelCard
import adws_quick_backend as backend


class Host(Gtk.Window):
    closed = False
    def after_motion(self, callback): GLib.idle_add(callback)


def pump(seconds):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        while Gtk.events_pending(): Gtk.main_iteration()
        time.sleep(.005)


calls = []
def read(**kwargs):
    calls.append(kwargs.get('passive', False))
    return [dict(name='DP-1', description='Fixture', provider='ddc', value=55)]


with patch.object(backend, 'brightness', side_effect=read), \
        patch.object(backend, 'cached_brightness', return_value=None):
    host = Host()
    control = LevelCard(host, 'brightness')
    host.add(control.box)
    host.show_all()
    pump(6.5)
    assert calls and calls[0] is False, calls
    assert len(calls) >= 2 and all(calls[1:]), calls
    control.refresh()
    pump(.2)
    assert calls[-1] is False, calls
    host.hide()
    pump(.1)
    assert control.poll_source == 0
    host.destroy()
print('PASS: initial/manual reads active; periodic reads passive; hide cancels polling')

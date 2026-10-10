"""Run with dbus-run-session and Xvfb: separate launches reuse one window."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


def child(role, marker, tab, start_instance=""):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    from adws_system_settings import run_settings
    Gtk.init([])

    def record(text):
        with open(marker, 'a') as stream:
            stream.write(text + '\n')

    class Window(Gtk.Window):
        def __init__(self, config, tab=None):
            if role != 'primary':
                raise AssertionError('Repeated launch created another window')
            super().__init__()
            self.rows = {'wallpaper': None, 'sound': None, 'start': None}
            self.pending = {'keep this edit'}
            self.connect('destroy', lambda *_: Gtk.main_quit())
            self.show_all()
            record('created')
            GLib.timeout_add_seconds(15, self.finish)

        def show_page(self, key):
            assert self.pending == {'keep this edit'}
            record('page:' + key)
            if key == 'sound':
                GLib.timeout_add(200, self.finish)

        def select_start_instance(self, instance):
            assert self.pending == {'keep this edit'}
            record('instance:' + instance)

        def present(self):
            record('present')
            super().present()

        def finish(self):
            self.destroy()
            return False

    return run_settings(None, tab=tab or None, window_factory=Window, start_instance=start_instance or None)


def main():
    assert os.environ.get('DBUS_SESSION_BUS_ADDRESS'), 'Use an isolated dbus-run-session'
    with tempfile.TemporaryDirectory(prefix='adws-settings-instance-') as folder:
        marker = Path(folder) / 'events'
        primary = subprocess.Popen([sys.executable, __file__, '--child', 'primary', str(marker), ''])
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if marker.exists() and 'created' in marker.read_text():
                    break
                if primary.poll() is not None:
                    raise AssertionError('Primary window exited early')
                time.sleep(.05)
            else:
                raise AssertionError('Primary window did not start')
            for tab, instance in (('', ''), ('wallpaper', ''), ('start', 'start'), ('start', 'start-other'), ('sound', '')):
                subprocess.run([sys.executable, __file__, '--child', 'secondary', str(marker), tab, instance], check=True, timeout=10)
            assert primary.wait(timeout=10) == 0
            events = marker.read_text().splitlines()
            assert events.count('created') == 1, events
            assert events.count('present') == 6, events
            assert [event for event in events if event.startswith('page:')] == ['page:wallpaper', 'page:start', 'page:start', 'page:sound'], events
            assert [event for event in events if event.startswith('instance:')] == ['instance:start', 'instance:start-other'], events
            print('PASS repeated launches reuse one window and retain pending edits')
        finally:
            if primary.poll() is None:
                primary.terminate()
                primary.wait(timeout=5)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        raise SystemExit(child(*sys.argv[2:]))
    main()

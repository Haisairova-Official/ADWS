"""Exercise ADWS settings and both folder entry points on a private GTK display."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def recorders(root):
    applications = root / 'data/applications'
    applications.mkdir(parents=True)
    logger = root / 'record.py'
    logger.write_text(
        'import json, os, sys\n'
        'with open(os.environ["ADWS_TEST_OPENS"], "a") as f:\n'
        '    print(json.dumps(sys.argv[1:]), file=f)\n'
    )
    for name in ('first', 'second'):
        (applications / f'adws-test-{name}.desktop').write_text(
            '[Desktop Entry]\nType=Application\n'
            f'Name=Fixture {name}\nExec="{sys.executable}" "{logger}" {name} %U\n'
            'Categories=System;FileManager;\nMimeType=inode/directory;\n'
        )


def choose_manager(desktop_id):
    import gi
    gi.require_version('Gtk', '3.0')
    from adws_settings_widgets import ApplicationChoice
    from adws_system_settings import SystemSettingsWindow
    content_type = 'inode/directory'
    chooser = ApplicationChoice(content_type)
    chooser.set_active_id(next(key for key, app in chooser.apps.items() if app.get_id() == desktop_id))
    SystemSettingsWindow.apply_apps(SimpleNamespace(app_dirty={content_type}, app_choices={content_type: chooser}))
    chooser.destroy()


def exercise(root):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gio, GLib, Gtk
    from adws_desktop_groups import Card
    from desktop_layer.model import launch_entry, scan_desktop

    folder = root/'Desktop'/'组 内文件夹'
    folder.mkdir(parents=True)
    entry, = scan_desktop(folder.parent)
    widget = Gtk.Button()
    content_type = 'inode/directory'
    log = Path(os.environ['ADWS_TEST_OPENS'])
    count = 0

    def verify(action, name):
        nonlocal count
        action()
        count += 1
        end = time.monotonic() + 5
        while time.monotonic() < end:
            while GLib.MainContext.default().iteration(False):
                pass
            lines = log.read_text().splitlines() if log.exists() else []
            if len(lines) == count:
                who, location = json.loads(lines[-1])
                assert who == name and Gio.File.new_for_commandline_arg(location).get_path() == str(folder), lines
                return
            time.sleep(.02)
        raise AssertionError(f'{name}: expected launch {count}')

    for name in ('first', 'second'):
        desktop_id = f'adws-test-{name}.desktop'
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--choose', desktop_id], check=True)
        end = time.monotonic() + 3
        while time.monotonic() < end:
            while GLib.MainContext.default().iteration(False):
                pass
            default = Gio.AppInfo.get_default_for_type(content_type, False)
            if default and default.get_id() == desktop_id:
                break
            time.sleep(.02)
        assert Gio.AppInfo.get_default_for_type(content_type, False).get_id() == desktop_id
        verify(lambda: launch_entry(entry), name)
        verify(lambda: Card.open_directory(widget, folder), name)
    print('PASS: changing the file manager in ADWS switches both desktop and group folder launches')


if __name__ == '__main__':
    sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src/niri-desktop-layer')]
    if sys.argv[1:2] == ['--choose']:
        choose_manager(sys.argv[2])
    elif len(sys.argv) == 2:
        exercise(Path(sys.argv[1]))
    else:
        with tempfile.TemporaryDirectory(prefix='adws-file-manager-') as directory:
            root = Path(directory)
            recorders(root)
            (root/'runtime').mkdir(mode=0o700)
            env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(root/'config'),
                       XDG_DATA_HOME=str(root/'data'), XDG_STATE_HOME=str(root/'state'),
                       XDG_CACHE_HOME=str(root/'cache'), XDG_RUNTIME_DIR=str(root/'runtime'),
                       GDK_BACKEND='x11', GTK_USE_PORTAL='0', GIO_USE_VFS='local',
                       ADWS_TEST_OPENS=str(root/'opens'))
            subprocess.run(['dbus-run-session', '--', 'xvfb-run', '-a', sys.executable,
                            str(Path(__file__).resolve()), directory], env=env, check=True)

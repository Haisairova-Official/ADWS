"""Live GTK3 user-theme reload, including imported and atomically replaced files."""
from pathlib import Path
import os
import re

_IMPORT = re.compile(r'@import\s+(?:url\(\s*)?[\"\']([^\"\']+)[\"\']\s*\)?\s*;')
_watchers = []


def css_snapshot(paths):
    """Use contents, not inode watches: generators often replace a symlink/file."""
    result = {}
    def visit(path):
        path = Path(os.path.abspath(path))
        if path in result:
            return
        try:
            data = path.read_bytes()
        except OSError:
            data = None
        result[path] = data
        if data is not None:
            for name in _IMPORT.findall(data.decode('utf-8', errors='replace')):
                if '://' not in name:
                    visit(path.parent / name)
    for path in paths:
        visit(path)
    return result


class Watch:
    def __init__(self, paths, callback, owner=None):
        from gi.repository import GLib
        self.paths, self.callback = paths, callback
        self.snapshot = css_snapshot(paths)
        self.source = GLib.timeout_add(500, self.poll)
        if owner is not None:
            owner.connect('destroy', lambda *_: self.close())

    def poll(self):
        current = css_snapshot(self.paths)
        if current != self.snapshot:
            if self.callback() is not False:
                self.snapshot = current
        return True

    def close(self):
        from gi.repository import GLib
        if self.source:
            GLib.source_remove(self.source)
            self.source = 0
        self.callback = lambda: None


def start():
    """Once per GUI process; respect the user's existing GTK stylesheet."""
    if _watchers:
        return
    from gi.repository import Gtk, Gdk
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    path = config / 'gtk-3.0/gtk.css'
    provider = [None]

    def reload():
        candidate = Gtk.CssProvider()
        try:
            if path.exists():
                candidate.load_from_path(str(path))
        except Exception:
            return False  # Keep the last valid palette during a partial write.
        Gtk.StyleContext.add_provider_for_screen(screen, candidate, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        if provider[0] is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, provider[0])
        provider[0] = candidate
        Gtk.StyleContext.reset_widgets(screen)
        for window in Gtk.Window.list_toplevels():
            window.queue_draw()
        return True

    reload()
    _watchers.append(Watch([path], reload))

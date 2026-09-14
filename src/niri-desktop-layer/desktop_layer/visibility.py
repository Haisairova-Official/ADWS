"""Follow the existing Waybar visibility marker without changing its script."""
from .i18n import tr as _tr
from pathlib import Path
import logging
from gi.repository import Gio, GLib

LOG = logging.getLogger("desktop-layer.visibility")


class WindowFade:
    """Fade icons while keeping the desktop surface available for its menu."""
    def __init__(self, window, content, hidden=False):
        self.window, self.content = window, content
        self.pending = 0
        self.hidden = hidden
        content.set_opacity(0.0 if hidden else 1.0)
        content.set_sensitive(True)

    def set_hidden(self, hidden):
        self.close()
        self.hidden = hidden
        self.start_opacity = self.content.get_opacity()
        self.target = 0.0 if hidden else 1.0
        self.started = GLib.get_monotonic_time()
        self.content.set_sensitive(True)
        self.window.show_all()
        self.pending = GLib.timeout_add(16, self.step)

    def step(self):
        t = min(1.0, (GLib.get_monotonic_time() - self.started) / 220000)
        eased = t * t * (3 - 2 * t)
        self.content.set_opacity(self.start_opacity + (self.target - self.start_opacity) * eased)
        if t < 1.0:
            return True
        self.pending = 0
        return False

    def close(self):
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0


class MarkerVisibility:
    def __init__(self, marker, callback):
        self.marker = Path(marker).expanduser().absolute()
        self.callback = callback
        self.monitor = None
        self.pending = 0
        self.closed = True

    def start(self):
        if not self.closed:
            return self
        self.closed = False
        try:
            self.monitor = Gio.File.new_for_path(str(self.marker)).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self.monitor.connect("changed", self.changed)
        except GLib.Error as error:
            LOG.warning(_tr('无法监听任务栏状态 %s: %s'), self.marker, error.message)
        self.sync()
        return self

    def changed(self, _monitor, file, other_file, _event):
        if self.closed or not any(f is not None and f.get_path() == str(self.marker) for f in (file, other_file)):
            return
        if not self.pending:
            self.pending = GLib.timeout_add(40, self.sync)

    def sync(self):
        self.pending = 0
        if not self.closed:
            # Match the existing shell script's `test -f`; apply state, never toggle.
            self.callback(self.marker.is_file())
        return False

    def close(self):
        self.closed = True
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0
        if self.monitor is not None:
            self.monitor.cancel()
            self.monitor = None

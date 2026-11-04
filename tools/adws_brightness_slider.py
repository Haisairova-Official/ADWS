"""Keep pointer motion local; commit slow monitor brightness after interaction."""
from gi.repository import GLib


class HardwareSlider:
    def __init__(self, scale, commit, enabled=lambda: True):
        self.scale = scale
        self.commit = commit
        self.enabled = enabled
        self.dragging = False
        self.pending = None
        self.timer = 0
        self.updating = False
        scale.connect('button-press-event', self.press)
        scale.connect('button-release-event', self.release)
        scale.connect('grab-broken-event', self.release)
        scale.connect('value-changed', self.changed)
        scale.connect('unmap', self.unmap)
        scale.connect('destroy', self.unmap)

    def cancel_timer(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def press(self, _, event):
        if event.button == 1 and self.enabled():
            self.dragging = True
            self.cancel_timer()
        return False

    def release(self, *_):
        self.dragging = False
        # GTK may apply its final adjustment after this event handler.
        if self.pending is not None and not self.timer:
            self.timer = GLib.idle_add(self.flush)
        return False

    def changed(self, scale):
        if self.updating: return
        if not self.enabled():
            self.commit(scale.get_value())
            return
        self.pending = scale.get_value()
        self.cancel_timer()
        if not self.dragging:
            self.timer = GLib.timeout_add(250, self.flush)

    def flush(self):
        self.cancel_timer()
        value, self.pending = self.pending, None
        if value is not None: self.commit(value)
        return False

    def unmap(self, *_):
        self.dragging = False
        self.flush()

    def set_value(self, value):
        # A background status refresh must not move a slider being edited.
        if self.dragging or self.pending is not None: return
        self.updating = True
        try: self.scale.set_value(value)
        finally: self.updating = False

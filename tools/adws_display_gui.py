"""Display arrangement editor with staged per-monitor changes and safe previews."""
import copy
import math
import re
import time

import gi
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gdk, GLib, GObject, Gtk, Pango, PangoCairo

import adws_display as backend
from adws_i18n import tr


def caption(text, style=None):
    widget = Gtk.Label(label=tr(text), xalign=0)
    widget.set_line_wrap(True)
    if style:
        widget.get_style_context().add_class(style)
    return widget


def section(title, description=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    box.get_style_context().add_class('settings-card')
    box.pack_start(caption(title, 'settings-section-title'), False, False, 0)
    if description:
        box.pack_start(caption(description, 'settings-caption'), False, False, 0)
    return box


def round_rectangle(cr, x, y, width, height, radius=12):
    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    for cx, cy, first in ((x + width - radius, y + radius, -90),
                          (x + width - radius, y + height - radius, 0),
                          (x + radius, y + height - radius, 90),
                          (x + radius, y + radius, 180)):
        cr.arc(cx, cy, radius, math.radians(first), math.radians(first + 90))
    cr.close_path()


class NumericChoice(Gtk.ComboBoxText):
    """Editable numeric presets; invalid drafts never replace the last value."""
    __gsignals__ = {'input-changed': (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, unit, minimum, maximum, presets=(), available_only=False):
        super().__init__(has_entry=True)
        self.unit, self.minimum, self.maximum = unit, minimum, maximum
        self.available_only = available_only
        self.presets, self.value, self.invalid, self.setting = [], minimum, False, False
        self.get_child().set_width_chars(12)
        self.get_child().set_max_length(32)
        self.connect('changed', self.changed)
        self.get_child().connect('activate', self.normalize)
        self.get_child().connect('focus-out-event', self.normalize)
        self.set_presets(presets)

    @staticmethod
    def number(value):
        return f'{value:.3f}'.rstrip('0').rstrip('.')

    def set_presets(self, values):
        self.setting = True
        try:
            self.remove_all()
            self.presets = list(values)
            for value in self.presets:
                self.append(self.number(value), f'{self.number(value)} {self.unit}'.strip())
        finally:
            self.setting = False

    def bind_editor(self, adapter):
        adapter._connect(adapter.editor, 'activate', self.normalize)
        adapter._connect(adapter.editor, 'focus-out-event', self.normalize)

    def set_value(self, value):
        self.setting = True
        try:
            self.value = float(value)
            if not self.set_active_id(self.number(self.value)):
                self.set_active(-1)
                self.get_child().set_text(f'{self.number(self.value)} {self.unit}'.strip())
            self.set_error(False)
        finally:
            self.setting = False
        self.emit('input-changed')

    def get_value(self):
        return self.value

    def set_error(self, invalid):
        self.invalid = invalid
        entries = [self.get_child()]
        adapter = getattr(self, '_adws_choice_button', None)
        if adapter is not None and adapter.editor is not None:
            entries.append(adapter.editor)
        for entry in entries:
            context = entry.get_style_context()
            context.add_class('error') if invalid else context.remove_class('error')

    def changed(self, *_):
        if self.setting:
            return
        text = self.get_child().get_text().strip()
        suffix = self.unit.casefold()
        if text.casefold().endswith(suffix):
            text = text[:-len(suffix)].strip()
        valid = bool(re.fullmatch(r'\d+(?:[.,]\d+)?', text))
        value = float(text.replace(',', '.')) if valid else None
        valid = valid and self.minimum <= value <= self.maximum
        if valid and self.available_only:
            matches = [preset for preset in self.presets if abs(preset-value) <= .005]
            valid = bool(matches)
            if valid:
                value = min(matches, key=lambda preset: abs(preset-value))
        self.set_error(not valid)
        if valid:
            self.value = value
        self.emit('input-changed')

    def normalize(self, *_):
        if not self.invalid:
            self.set_value(self.value)
        return False


class MonitorCanvas(Gtk.DrawingArea):
    """Always drag in a fixed viewport; refit only after the pointer is released."""
    def __init__(self, selected, changed):
        super().__init__()
        self.monitors, self.selected = [], None
        self.on_selected, self.on_changed = selected, changed
        self.viewport = (1, 0, 0)
        self.drag = None
        self.set_size_request(-1, 250)
        self.set_hexpand(True)
        self.set_can_focus(True)
        self.get_accessible().set_name(tr('显示器排列'))
        self.get_accessible().set_description(tr('拖动显示器调整位置，也可以用方向键微调。'))
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect('draw', self.draw)
        self.connect('button-press-event', self.press)
        self.connect('motion-notify-event', self.motion)
        self.connect('button-release-event', self.release)
        self.connect('key-press-event', self.key_pressed)

    def set_monitors(self, monitors, selected):
        self.monitors, self.selected = monitors, selected
        self.queue_draw()

    def fit(self):
        x, y, width, height = backend.layout_bounds(self.monitors)
        space_w, space_h = max(1, self.get_allocated_width() - 88), max(1, self.get_allocated_height() - 64)
        scale = min(space_w / width, space_h / height)
        self.viewport = (scale, (self.get_allocated_width() - width * scale) / 2 - x * scale,
                         (self.get_allocated_height() - height * scale) / 2 - y * scale)

    def rectangle(self, monitor):
        scale, x, y = self.viewport
        width, height = backend.logical_size(monitor)
        return monitor['x'] * scale + x, monitor['y'] * scale + y, width * scale, height * scale

    def color(self, name, fallback):
        found, value = self.get_style_context().lookup_color(name)
        if found:
            return value.red, value.green, value.blue, value.alpha
        value = Gdk.RGBA(); value.parse(fallback)
        return value.red, value.green, value.blue, value.alpha

    def draw_text(self, cr, text, x, y, width, size, color, bold=False):
        layout = self.create_pango_layout(text)
        font = self.get_pango_context().get_font_description().copy()
        font.set_size(size * Pango.SCALE)
        if bold:
            font.set_weight(Pango.Weight.BOLD)
        layout.set_font_description(font)
        layout.set_width(max(1, int(width)) * Pango.SCALE)
        layout.set_alignment(Pango.Alignment.CENTER)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        cr.set_source_rgba(*color); cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)

    def draw(self, _, cr):
        if not self.drag:
            self.fit()
        bg = self.color('adws_settings_bg', '#202020')
        surface = self.color('adws_settings_surface', '#363636')
        accent = self.color('adws_settings_accent', '#e1af96')
        foreground = self.color('adws_settings_text', '#eeeeee')
        selected_text = self.color('adws_settings_on_accent', '#202020')
        outline = self.color('adws_settings_outline', '#888888')
        cr.set_source_rgba(*bg)
        round_rectangle(cr, 0, 0, self.get_allocated_width(), self.get_allocated_height(), 14); cr.fill()
        cr.set_source_rgba(*outline[:3], .15)
        for x in range(16, self.get_allocated_width(), 24):
            for y in range(16, self.get_allocated_height(), 24):
                cr.arc(x, y, .75, 0, math.tau); cr.fill()
        if not self.monitors:
            self.draw_text(cr, tr('正在读取显示器…'), 0, self.get_allocated_height()/2 - 8,
                           self.get_allocated_width(), 11, foreground)
        ordered = [m for m in self.monitors if m['name'] != self.selected]
        ordered.extend(m for m in self.monitors if m['name'] == self.selected)
        for monitor in ordered:
            x, y, width, height = self.rectangle(monitor)
            is_selected = monitor['name'] == self.selected
            inset = min(3, width / 6, height / 6)
            round_rectangle(cr, x + inset, y + inset, max(1, width-2*inset), max(1, height-2*inset), 10)
            cr.set_source_rgba(*(accent if is_selected else surface)); cr.fill_preserve()
            cr.set_source_rgba(*(accent if is_selected else outline)); cr.set_line_width(2); cr.stroke()
            color = selected_text if is_selected else foreground
            if height > 40:
                number = self.monitors.index(monitor) + 1
                self.draw_text(cr, str(number), x + 8, y + height/2 - 28, width - 16,
                               24 if height > 100 else 16, color, True)
                self.draw_text(cr, monitor['name'], x + 8, y + height/2 + 9, width - 16, 10, color)
        return False

    def press(self, _, event):
        if event.button != 1:
            return False
        self.grab_focus()
        ordered = [m for m in self.monitors if m['name'] != self.selected]
        ordered.extend(m for m in self.monitors if m['name'] == self.selected)
        for monitor in reversed(ordered):
            x, y, width, height = self.rectangle(monitor)
            if x <= event.x <= x+width and y <= event.y <= y+height:
                self.selected = monitor['name']
                self.drag = (monitor, event.x, event.y, monitor['x'], monitor['y'])
                self.on_selected(monitor['name']); self.queue_draw()
                return True
        return False

    def motion(self, _, event):
        if not self.drag:
            return False
        monitor, start_x, start_y, old_x, old_y = self.drag
        scale = self.viewport[0]
        x, y = old_x + (event.x-start_x)/scale, old_y + (event.y-start_y)/scale
        monitor['x'], monitor['y'] = backend.snapped_position(monitor, self.monitors, x, y, 12/scale)
        self.on_changed(); self.queue_draw()
        return True

    def release(self, _, event):
        if event.button != 1 or not self.drag:
            return False
        self.drag = None
        self.queue_draw()
        return True

    def key_pressed(self, _, event):
        movement = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if event.keyval not in movement:
            return False
        monitor = next((m for m in self.monitors if m['name'] == self.selected), None)
        if not monitor:
            return False
        amount = 10 if event.state & Gdk.ModifierType.SHIFT_MASK else 1
        dx, dy = movement[event.keyval]
        monitor['x'] = max(-32768, min(32768, monitor['x'] + dx * amount))
        monitor['y'] = max(-32768, min(32768, monitor['y'] + dy * amount))
        self.on_changed(); self.queue_draw()
        return True


class DisplaySettingsPage(Gtk.Box):
    def __init__(self, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.host = host
        self.original, self.pending = [], []
        self.selected = None
        self.loading = False
        self.loaded = False
        self.active = True
        self.preview_timer = 0
        self.input_drafts = {}
        self.connect('destroy', self.destroyed)
        arrangement = section('排列显示器', '拖动显示器调整位置；靠近边缘时自动吸附。点击显示器可单独设置。')
        self.canvas = MonitorCanvas(self.select_monitor, self.canvas_changed)
        arrangement.pack_start(self.canvas, True, True, 0)
        self.monitor_buttons = Gtk.Box(spacing=8)
        arrangement.pack_start(self.monitor_buttons, False, False, 0)
        toolbar = Gtk.Box(spacing=8)
        self.layout_status = caption('正在读取显示器…', 'settings-caption')
        toolbar.pack_start(self.layout_status, True, True, 0)
        refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text(tr('重新检测显示器')); refresh.connect('clicked', self.refresh)
        toolbar.pack_end(refresh, False, False, 0)
        arrangement.pack_start(toolbar, False, False, 0)
        self.pack_start(arrangement, False, False, 0)
        self.details = section('显示器设置')
        self.monitor_title = caption('', 'settings-section-title')
        self.details.pack_start(self.monitor_title, False, False, 0)
        self.monitor_description = caption('', 'settings-caption')
        self.details.pack_start(self.monitor_description, False, False, 0)
        self.resolution = Gtk.MenuButton()
        self.resolution.set_size_request(170, -1)
        self.resolution_popover = Gtk.Popover.new(self.resolution)
        self.resolution_popover.get_style_context().add_class('adws-settings-popover')
        self.resolution.set_popover(self.resolution_popover)
        self.resolution_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(300); scroll.set_propagate_natural_height(True)
        scroll.add(self.resolution_list); self.resolution_popover.add(scroll)
        self.add_row('分辨率', self.resolution)
        self.refresh_rate = NumericChoice('Hz', .001, 2000, available_only=True)
        self.refresh_rate.connect('input-changed', self.numeric_changed, 'refresh')
        self.add_row('刷新率', self.refresh_rate)
        self.scale = NumericChoice('%', 50, 400, (100, 125, 150, 175, 200))
        self.scale.connect('input-changed', self.numeric_changed, 'scale')
        self.add_row('缩放', self.scale)
        self.rotation_choices = self.flow()
        self.rotation_buttons = {}
        for index, title in enumerate(('横向', '向左旋转', '倒置', '向右旋转')):
            button = Gtk.ToggleButton(label=tr(title))
            button.connect('clicked', self.rotation_changed, index)
            self.rotation_choices.add(button); self.rotation_buttons[index] = button
        self.add_row('旋转', self.rotation_choices)
        self.mirror = Gtk.Switch(); self.mirror.set_halign(Gtk.Align.START); self.mirror.set_valign(Gtk.Align.CENTER)
        self.mirror.connect('notify::active', self.field_changed)
        self.add_row('水平翻转', self.mirror)
        coordinates = Gtk.Box(spacing=8)
        self.x, self.y = Gtk.SpinButton.new_with_range(-32768, 32768, 1), Gtk.SpinButton.new_with_range(-32768, 32768, 1)
        for name, spin in (('X', self.x), ('Y', self.y)):
            spin.set_width_chars(6); spin.connect('value-changed', self.field_changed)
            coordinates.pack_start(Gtk.Label(label=name), False, False, 0)
            coordinates.pack_start(spin, True, True, 0)
        self.add_row('精确位置', coordinates)
        self.input_error = caption('请修正刷新率或缩放输入；刷新率须为当前分辨率支持的值，缩放范围为 50%–400%。', 'settings-input-error')
        self.input_error.set_no_show_all(True)
        self.details.pack_start(self.input_error, False, False, 0)
        self.pack_start(self.details, False, False, 0)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        footer.pack_start(caption('显示更改仅用于当前会话。测试后有 15 秒确认，未确认会恢复全部显示器。', 'settings-caption'), False, False, 0)
        actions = Gtk.Box(spacing=8)
        reset = Gtk.Button(label=tr('撤销排列修改')); reset.connect('clicked', lambda *_: self.discard_changes())
        self.test_button = Gtk.Button(label=tr('测试显示设置')); self.test_button.get_style_context().add_class('suggested-action')
        self.test_button.connect('clicked', self.test_changes)
        actions.pack_end(self.test_button, False, False, 0); actions.pack_end(reset, False, False, 0)
        footer.pack_start(actions, False, False, 0); self.pack_start(footer, False, False, 0)
        self.details.set_sensitive(False); self.test_button.set_sensitive(False)
        GLib.idle_add(self.refresh)

    @staticmethod
    def flow():
        flow = Gtk.FlowBox(); flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_column_spacing(6); flow.set_row_spacing(6)
        flow.set_min_children_per_line(1); flow.set_max_children_per_line(6)
        return flow

    def add_row(self, title, control):
        row = Gtk.Box(spacing=18)
        title_label = caption(title); title_label.set_size_request(100, -1)
        title_label.set_valign(Gtk.Align.START); title_label.set_margin_top(8)
        row.pack_start(title_label, False, False, 0); row.pack_start(control, True, True, 0)
        self.details.pack_start(row, False, False, 0)

    def refresh(self, *_):
        if not self.active or self.host.closed or self.host.busy:
            return False
        if self.has_pending() and not self.host.confirm('重新检测并放弃显示修改？', '尚未测试的排列与显示参数会被清除。'):
            return False
        result = []
        def job():
            result.extend(backend.outputs(self.host.display_session))
        def success():
            if self.active:
                self.set_outputs(result)
        self.host.run_worker(job, success)
        return False

    def set_outputs(self, monitors):
        self.input_drafts.clear()
        self.original = copy.deepcopy(monitors)
        self.pending = copy.deepcopy(monitors)
        self.loaded = True
        if self.selected not in [m['name'] for m in monitors]:
            self.selected = monitors[0]['name'] if monitors else None
        for child in self.monitor_buttons.get_children():
            child.destroy()
        for index, monitor in enumerate(monitors):
            button = Gtk.ToggleButton(label=f"{index+1}  {monitor['name']}")
            button.connect('clicked', self.monitor_clicked, monitor['name'])
            self.monitor_buttons.pack_start(button, False, False, 0)
        self.monitor_buttons.show_all()
        self.details.set_sensitive(bool(monitors))
        self.select_monitor(self.selected)
        self.update_dirty()

    def monitor_clicked(self, _, name):
        if not self.loading:
            self.select_monitor(name)

    def current(self):
        return next((m for m in self.pending if m['name'] == self.selected), None)

    def select_monitor(self, name):
        self.selected = name
        self.canvas.set_monitors(self.pending, name)
        monitor = self.current()
        if not monitor:
            self.layout_status.set_text(tr('没有检测到已启用的显示器。'))
            return
        self.loading = True
        try:
            for index, child in enumerate(self.monitor_buttons.get_children()):
                child.set_active(self.pending[index]['name'] == name)
            self.monitor_title.set_text(name)
            self.monitor_description.set_text(monitor.get('description', ''))
            self.populate_modes(monitor)
            self.scale.set_value(monitor['scale'] * 100)
            for field, control in (('refresh', self.refresh_rate), ('scale', self.scale)):
                draft = self.input_drafts.get((name, field))
                if draft is not None:
                    control.get_child().set_text(draft)
            for index, button in self.rotation_buttons.items():
                button.set_active(monitor['transform'] % 4 == index)
            self.mirror.set_active(monitor['transform'] >= 4)
            self.x.set_value(monitor['x']); self.y.set_value(monitor['y'])
        finally:
            self.loading = False

    def populate_modes(self, monitor):
        width, height, refresh = backend.parse_mode(monitor['mode'])
        self.resolution.set_label(f'{width} × {height}  ▾')
        modes = [backend.parse_mode(m) for m in monitor['modes']]
        for child in self.resolution_list.get_children():
            child.destroy()
        for w, h in sorted({(m[0], m[1]) for m in modes}, key=lambda pair: pair[0]*pair[1], reverse=True):
            button = Gtk.Button(label=f'{w} × {h}')
            if (w, h) == (width, height):
                button.get_style_context().add_class('suggested-action')
            button.connect('clicked', self.resolution_changed, w, h)
            self.resolution_list.pack_start(button, False, False, 0)
        self.resolution_list.show_all()
        self.refresh_rate.set_presets(sorted({m[2] for m in modes if m[:2] == (width, height)}, reverse=True))
        self.refresh_rate.set_value(refresh)

    def resolution_changed(self, _, width, height):
        monitor = self.current()
        if not monitor:
            return
        previous_rate = backend.parse_mode(monitor['mode'])[2]
        options = [m for m in monitor['modes'] if backend.parse_mode(m)[:2] == (width, height)]
        monitor['mode'] = min(options, key=lambda m: abs(backend.parse_mode(m)[2] - previous_rate))
        self.input_drafts.pop((self.selected, 'refresh'), None)
        self.resolution_popover.popdown()
        self.select_monitor(self.selected); self.update_dirty()

    def numeric_changed(self, control, field):
        if self.loading or not self.current():
            return
        monitor = self.current()
        key = (self.selected, field)
        if control.invalid:
            self.input_drafts[key] = control.get_child().get_text()
        else:
            self.input_drafts.pop(key, None)
            if field == 'scale':
                monitor['scale'] = control.get_value()/100
                self.canvas.queue_draw()
            else:
                size = backend.parse_mode(monitor['mode'])[:2]
                monitor['mode'] = next(m for m in monitor['modes'] if backend.parse_mode(m) == (*size, control.get_value()))
        self.update_dirty()

    def rotation_changed(self, _, index):
        if self.loading or not self.current():
            return
        self.current()['transform'] = index + (4 if self.mirror.get_active() else 0)
        self.select_monitor(self.selected); self.update_dirty()

    def field_changed(self, *_):
        if self.loading or not self.current():
            return
        monitor = self.current()
        monitor.update(x=self.x.get_value_as_int(), y=self.y.get_value_as_int(),
                       transform=monitor['transform'] % 4 + (4 if self.mirror.get_active() else 0))
        self.canvas.queue_draw()
        self.update_dirty()

    def canvas_changed(self):
        monitor = self.current()
        if not monitor:
            return
        self.loading = True
        self.x.set_value(monitor['x']); self.y.set_value(monitor['y'])
        self.loading = False
        self.update_dirty()

    def has_pending(self):
        return bool(self.input_drafts) or (len(self.original) == len(self.pending) and any(not backend.same_settings(old, new) for old, new in zip(self.original, self.pending)))

    def update_dirty(self):
        dirty = self.has_pending()
        if dirty:
            self.host.mark_dirty('displays')
        else:
            self.host.dirty.discard('displays')
            self.host.update_footer()
        self.test_button.set_sensitive(dirty and not self.input_drafts)
        self.input_error.set_visible(bool(self.input_drafts))
        if self.pending:
            text = tr('排列已修改，测试后生效。') if dirty else tr('%s 个显示器 · 拖动排列') % len(self.pending)
            self.layout_status.set_text(text)

    def discard_changes(self):
        self.set_outputs(self.original)

    def test_changes(self, *_):
        if self.host.busy or self.input_drafts or not self.has_pending():
            return
        old, new = copy.deepcopy(self.original), copy.deepcopy(self.pending)
        touched = []
        def job():
            current = backend.outputs(self.host.display_session)
            mapped = {m['name']: m for m in current}
            if set(mapped) != {m['name'] for m in old} or any(not backend.same_settings(m, mapped[m['name']]) for m in old):
                raise RuntimeError(tr('显示器状态已在其他地方更改，请重新检测后再试。'))
            touched.extend(backend.preview_all(self.host.display_session, old, new))
        def shown():
            self.ask_keep(old, new, touched)
        self.host.run_worker(job, shown)

    def ask_keep(self, old, new, touched):
        dialog = Gtk.MessageDialog(transient_for=self.host, modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.QUESTION, text=tr('保留显示设置？'))
        dialog.add_button(tr('恢复'), Gtk.ResponseType.CANCEL)
        dialog.add_button(tr('保留'), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        deadline = time.monotonic() + 15
        def tick():
            remaining = max(0, math.ceil(deadline-time.monotonic()))
            dialog.format_secondary_text(tr('%s 秒后自动恢复。') % remaining)
            if remaining == 0:
                self.preview_timer = 0
                dialog.response(Gtk.ResponseType.CANCEL)
                return False
            return True
        tick()
        self.preview_timer = GLib.timeout_add(200, tick)
        self.host.busy = True
        try:
            response = dialog.run()
        finally:
            self.host.busy = False
            if self.preview_timer:
                GLib.source_remove(self.preview_timer); self.preview_timer = 0
            dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.set_outputs(new)
        else:
            self.host.run_worker(lambda: backend.restore_all(self.host.display_session, touched),
                                 lambda: self.set_outputs(old))

    def destroyed(self, *_):
        self.active = False


# Catalogue entries are exported for the language catalogue maintenance tools.
TRANSLATIONS = {
    '%s 个显示器 · 拖动排列': '%s displays · Drag to arrange',
    '倒置': 'Upside down',
    '分辨率': 'Resolution',
    '刷新率': 'Refresh rate',
    '向右旋转': 'Rotate right',
    '向左旋转': 'Rotate left',
    '尚未测试的排列与显示参数会被清除。': 'Untested arrangement and display changes will be discarded.',
    '拖动显示器调整位置，也可以用方向键微调。': 'Drag displays to arrange them, or use the arrow keys for precise adjustments.',
    '拖动显示器调整位置；靠近边缘时自动吸附。点击显示器可单独设置。': 'Drag displays to arrange them. Nearby edges snap together. Select a display to adjust its settings.',
    '排列已修改，测试后生效。': 'Arrangement changed. Test to apply.',
    '排列显示器': 'Arrange displays',
    '撤销排列修改': 'Discard display changes',
    '显示器排列': 'Display arrangement',
    '显示器状态已在其他地方更改，请重新检测后再试。': 'Display settings changed elsewhere. Detect displays again before testing.',
    '显示器设置': 'Display settings',
    '显示更改仅用于当前会话。测试后有 15 秒确认，未确认会恢复全部显示器。': 'Changes apply to this session. You have 15 seconds to confirm; otherwise all displays are restored.',
    '横向': 'Landscape',
    '正在读取显示器…': 'Reading displays…',
    '水平翻转': 'Flip horizontally',
    '没有检测到已启用的显示器。': 'No enabled displays found.',
    '精确位置': 'Precise position',
    '重新检测并放弃显示修改？': 'Detect displays and discard changes?',
    '重新检测显示器': 'Detect displays again',
}

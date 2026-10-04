"""ADWS settings controls which preserve the existing configuration controllers.

``enhance_choices(page, translate=tr)`` upgrades ComboBoxText widgets, including editable font selectors.
The original combo remains hidden in its original parent, retaining its model,
signals, bindings, and all references held by configuration code.  Only its
presentation is replaced.  Call again after dynamically rebuilding a page.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango


class ApplicationChoice(Gtk.ComboBoxText):
    """One entry per installed application; selecting does not set defaults.

    GtkAppChooserButton can append its recommended/default groups twice during
    model updates. Own this model instead and use ADWS's standard choice popup.
    Compatible handlers come first; other visible applications remain available.
    """

    def __init__(self, content_type, applications=None, translate=lambda text: text):
        super().__init__()
        self.apps = {}
        default = Gio.AppInfo.get_default_for_type(content_type, False)
        compatible = Gio.AppInfo.get_all_for_type(content_type)
        installed = Gio.AppInfo.get_all() if applications is None else applications
        candidates = ([default] if default else []) + [app for app in compatible if app.should_show()] + sorted(
            (app for app in installed if app.should_show()),
            key=lambda app: (app.get_display_name().casefold(), app.get_id() or ''))
        selected = None
        seen = set()
        launches = set()
        for app in candidates:
            identity = ('id', app.get_id()) if app.get_id() else (
                'command', app.get_commandline(), app.get_display_name())
            # Some packages install a hidden alias and a visible launcher with
            # different IDs but the same name/command. Keep the current default
            # first, and don't offer that identical launcher a second time.
            command = app.get_commandline()
            launch = (app.get_display_name().casefold(), command) if command else None
            if identity in seen or (launch is not None and launch in launches):
                continue
            seen.add(identity)
            if launch is not None:
                launches.add(launch)
            key = str(len(self.apps))
            self.apps[key] = app
            self.append(key, app.get_display_name())
            if default and app.equal(default):
                selected = key
        if selected is not None:
            self.set_active_id(selected)
        else:
            # Opening the page must not choose an arbitrary default when the
            # system currently has no association for this content type.
            self.set_active(-1)
        if not self.apps:
            self.set_sensitive(False)
            self.set_tooltip_text(translate('没有可用的应用。'))

    def get_app_info(self):
        return self.apps.get(self.get_active_id())


class SelectionButton(Gtk.MenuButton):
    """A compact, searchable choice popover backed by an existing text combo.

    Styling hooks: ``adws-choice``, ``adws-choice-label``,
    ``adws-choice-popover``, ``adws-choice-list``, ``adws-choice-row``,
    ``adws-choice-check`` and ``adws-choice-empty``.
    """

    def __init__(self, combo: Gtk.ComboBoxText, translate=lambda text: text):
        super().__init__()
        self.combo = combo
        self.presentation = self
        self.editor = None
        self.tr = translate
        self._handlers = []
        self._model_handlers = []
        self._model = None
        self._sync_source = 0
        self._deferred_destroy = 0
        self._destroyed = False
        self._hiding_combo = False
        self._old_no_show_all = combo.get_no_show_all()
        self.get_style_context().add_class("adws-choice")
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.END)
        self.set_can_focus(True)

        contents = Gtk.Box(spacing=12)
        self.caption = Gtk.Label(xalign=0)
        self.caption.set_ellipsize(Pango.EllipsizeMode.END)
        self.caption.set_max_width_chars(28)
        self.caption.get_style_context().add_class("adws-choice-label")
        contents.pack_start(self.caption, True, True, 0)
        arrow = Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU)
        contents.pack_end(arrow, False, False, 0)
        self.add(contents)
        contents.show_all()

        self.popover = Gtk.Popover.new(self)
        self.popover.get_style_context().add_class("adws-choice-popover")
        self.popover.get_style_context().add_class("adws-settings-popover")
        self.popover.set_position(Gtk.PositionType.BOTTOM)
        self.set_popover(self.popover)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.set_border_width(8)
        self.popover.add(panel)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(self.tr("搜索选项…"))
        self.search.set_no_show_all(True)
        self.search.connect("search-changed", self._filter)
        self.search.connect("activate", self._activate_first)
        panel.pack_start(self.search, False, False, 0)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_max_content_height(360)
        self.scroll.set_propagate_natural_height(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.get_style_context().add_class("adws-choice-list")
        self.listbox.set_filter_func(self._matches)
        self.listbox.connect("row-activated", self._activate_row)
        self.scroll.add(self.listbox)
        panel.pack_start(self.scroll, True, True, 0)
        self.empty = Gtk.Label(label=self.tr("没有匹配的选项"))
        self.empty.get_style_context().add_class("adws-choice-empty")
        self.empty.set_no_show_all(True)
        panel.pack_start(self.empty, False, False, 0)
        panel.show_all()
        self.connect("toggled", self._toggled)
        self.connect("key-press-event", self._key_pressed)
        self.connect("destroy", self._dispose)
        self._connect(combo, "changed", self._sync)
        self._connect(combo, "notify::model", self._model_changed)
        self._connect(combo, "notify::sensitive", self._sync)
        self._connect(combo, "notify::tooltip-text", self._sync)
        self._connect(combo, "notify::visible", self._visibility_changed)
        self._connect(combo, "destroy", self._combo_destroyed)
        combo._adws_choice_button = self
        combo.set_no_show_all(True)
        self._hide_combo()
        self._model_changed()

    def _connect(self, obj, signal, callback):
        self._handlers.append((obj, obj.connect(signal, callback)))

    def _hide_combo(self):
        self._hiding_combo = True
        try:
            self.combo.hide()
        finally:
            self._hiding_combo = False

    def _visibility_changed(self, *_):
        if self._destroyed or self._hiding_combo:
            return
        visible = self.combo.get_visible()
        self.presentation.set_visible(visible)
        self.presentation.set_no_show_all(not visible)
        if visible:
            self._hide_combo()

    def _model_changed(self, *_):
        for model, handler in self._model_handlers:
            model.disconnect(handler)
        self._model_handlers.clear()
        self._model = self.combo.get_model()
        if self._model is not None:
            for signal in ("row-inserted", "row-deleted", "row-changed", "rows-reordered"):
                handler = self._model.connect(signal, self._queue_sync)
                self._model_handlers.append((self._model, handler))
        self._sync()

    def _queue_sync(self, *_):
        # remove_all()/append() may emit many model updates in the same turn.
        if not self._destroyed and not self._sync_source:
            self._sync_source = GLib.idle_add(self._flush_sync)

    def _flush_sync(self):
        self._sync_source = 0
        if not self._destroyed:
            self._sync()
        return GLib.SOURCE_REMOVE

    def _sync(self, *_):
        if self._destroyed:
            return
        caption = self.combo.get_active_text() or "—"
        self.caption.set_text(caption)
        self.presentation.set_sensitive(self.combo.get_sensitive())
        self.set_sensitive(self.combo.get_sensitive() and self._model is not None and len(self._model) > 0)
        self.set_tooltip_text(self.combo.get_tooltip_text())
        name = self.combo.get_accessible().get_name()
        self.get_accessible().set_name(f"{name}: {caption}" if name else caption)
        if self.get_active():
            self._rebuild_rows()

    def _rebuild_rows(self):
        for row in self.listbox.get_children():
            row.destroy()
        model = self._model
        self.search.set_visible(model is not None and len(model) >= 8)
        selected = self.combo.get_active()
        if selected < 0 and self.combo.get_has_entry() and model is not None:
            selected = next((index for index, item in enumerate(model)
                             if str(item[0] or "") == (self.combo.get_active_text() or "")), -1)
        selected_row = None
        if model is not None:
            for index, item in enumerate(model):
                row = Gtk.ListBoxRow()
                row.get_style_context().add_class("adws-choice-row")
                row.choice_ref = Gtk.TreeRowReference.new(model, item.path)
                row.choice_text = str(item[0] or "")
                line = Gtk.Box(spacing=18)
                line.set_border_width(4)
                title = Gtk.Label(label=row.choice_text, xalign=0)
                title.set_line_wrap(True)
                title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                # Full option text already wraps in the row. A redundant GTK
                # tooltip creates another popup surface, whose Wayland position
                # can drift away from a scrolled popover.
                title.set_width_chars(1)
                title.set_max_width_chars(1)
                row.choice_label = title
                line.pack_start(title, True, True, 0)
                check = Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU)
                check.get_style_context().add_class("adws-choice-check")
                check.set_opacity(1.0 if index == selected else 0.0)
                line.pack_end(check, False, False, 0)
                row.add(line)
                self.listbox.add(row)
                if index == selected:
                    selected_row = row
        self.listbox.show_all()
        self._size_popover()
        if selected_row is not None:
            self.listbox.select_row(selected_row)
        self._filter()

    def _size_popover(self):
        # min-content-width is ignored by GtkScrolledWindow with horizontal
        # policy NEVER. Set its actual minimum width, otherwise ellipsized/
        # wrapping labels collapse the entire popover to a few characters.
        toplevel = self.get_toplevel()
        window_width = toplevel.get_allocated_width()
        available = max(160, window_width - 36) if window_width > 1 else 420
        natural = 0
        if self._model is not None:
            for item in self._model:
                natural = max(natural, self.create_pango_layout(str(item[0] or "")).get_pixel_size()[0])
        width = min(420, available, max(240, self.presentation.get_allocated_width(), natural + 96))
        # The remaining width belongs to the popover's theme padding and panel.
        content_width = max(100, width - 58)
        height = min(360, max(44, self.listbox.get_preferred_height_for_width(content_width)[1]))
        self.scroll.set_size_request(content_width, height)
        self.scroll.set_min_content_width(content_width)
        self.scroll.set_min_content_height(-1)
        self.scroll.set_max_content_height(height)
        self.scroll.set_min_content_height(height)

    def _matches(self, row):
        query = self.search.get_text().casefold().strip()
        return all(word in row.choice_text.casefold() for word in query.split())

    def _filter(self, *_):
        self.listbox.invalidate_filter()
        self.empty.set_visible(not any(self._matches(row) for row in self.listbox.get_children()))

    def _toggled(self, *_):
        if not self.get_active() or self._destroyed:
            return
        self.search.set_text("")
        self._rebuild_rows()
        self._size_popover()
        if self.search.get_visible():
            self.search.grab_focus()
        else:
            row = self.listbox.get_selected_row() or self.listbox.get_row_at_index(0)
            if row is not None:
                row.grab_focus()

    def _activate_first(self, *_):
        row = next((row for row in self.listbox.get_children() if self._matches(row)), None)
        if row is not None:
            self._activate_row(self.listbox, row)

    def _activate_row(self, _listbox, row):
        reference = row.choice_ref
        if not reference.valid() or reference.get_model() is not self.combo.get_model():
            return
        model = reference.get_model()
        tree_iter = model.get_iter(reference.get_path())
        # Close first: a changed handler may immediately rebuild/destroy this
        # settings row (plugin placement does exactly that).
        self.set_active(False)
        self.combo.set_active_iter(tree_iter)
        if not self._destroyed:
            (self.editor or self).grab_focus()

    def _key_pressed(self, _button, event):
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_F4):
            self.set_active(True)
            return True
        if event.keyval == Gdk.KEY_Escape and self.get_active():
            self.set_active(False)
            return True
        return False

    def _combo_destroyed(self, *_):
        if self._destroyed:
            return
        # Combo and presentation are siblings. GtkBox may be iterating its
        # child list while destroying the combo (notably pack_end rows).
        # Synchronously destroying the next sibling invalidates that traversal
        # inside GTK. Disconnect immediately, then remove a surviving adapter
        # only after the container's disposal has finished.
        self._dispose()
        self._deferred_destroy = GLib.idle_add(self._destroy_presentation)

    def _destroy_presentation(self):
        self._deferred_destroy = 0
        self.presentation.destroy()
        return GLib.SOURCE_REMOVE

    def _dispose(self, *_):
        if self._deferred_destroy:
            GLib.source_remove(self._deferred_destroy)
            self._deferred_destroy = 0
        if self._destroyed:
            return
        self._destroyed = True
        if self._sync_source:
            GLib.source_remove(self._sync_source)
            self._sync_source = 0
        for obj, handler in self._handlers + self._model_handlers:
            if obj.handler_is_connected(handler):
                obj.disconnect(handler)
        self._handlers.clear()
        self._model_handlers.clear()
        self.popover.destroy()


def _insert_choice(combo, translate):
    """Keep the source control in place, preserving its original ancestry."""
    parent = combo.get_parent()
    if not isinstance(parent, (Gtk.Box, Gtk.Grid)):
        return None
    visible = combo.get_visible()
    no_show_all = combo.get_no_show_all()
    button = SelectionButton(combo, translate)
    presentation = button
    if combo.get_has_entry():
        # Both entries share the same GtkEntryBuffer: controller code reading
        # combo.get_child()/get_active_text() and existing changed handlers see
        # custom text immediately, just as with the original editable combo.
        original = combo.get_child()
        editor = Gtk.Entry(buffer=original.get_buffer())
        editor.set_width_chars(22)
        editor.set_max_width_chars(30)
        editor.set_placeholder_text(original.get_placeholder_text())
        editor.set_editable(original.get_editable())
        editor.set_tooltip_text(original.get_tooltip_text() or combo.get_tooltip_text())
        presentation = Gtk.Box(spacing=0)
        presentation.get_style_context().add_class("linked")
        presentation.get_style_context().add_class("adws-editable-choice")
        presentation.pack_start(editor, True, True, 0)
        presentation.pack_end(button, False, False, 0)
        button.caption.set_no_show_all(True)
        button.caption.hide()
        button.editor = editor
        button.presentation = presentation
        if hasattr(combo, 'bind_editor'):
            combo.bind_editor(button)
        button.popover.set_relative_to(presentation)
        button._connect(original, "notify::editable", lambda *_: editor.set_editable(original.get_editable()))
        presentation.show_all()
        button._sync()
    for prop in ("hexpand", "vexpand", "halign", "valign", "margin-start", "margin-end", "margin-top", "margin-bottom"):
        presentation.set_property(prop, combo.get_property(prop))
    # Keep choices compact and aligned even when the original combo occupied
    # an expanding row. Copying the old FILL alignment would undo this.
    presentation.set_halign(Gtk.Align.END)
    original_width, original_height = combo.get_size_request()
    presentation.set_size_request(max(240, original_width), original_height)
    if isinstance(parent, Gtk.Box):
        index = parent.get_children().index(combo)
        expand, fill, padding, pack_type = parent.query_child_packing(combo)
        if pack_type == Gtk.PackType.END:
            parent.pack_end(presentation, expand, fill, padding)
        else:
            parent.pack_start(presentation, expand, fill, padding)
        parent.reorder_child(presentation, index)
    else:
        values = [parent.child_get_property(combo, prop) for prop in ("left-attach", "top-attach", "width", "height")]
        parent.attach(presentation, *values)
    presentation.set_no_show_all(no_show_all)
    presentation.set_visible(visible)
    return button


def compact_switch(control):
    """Respect the switch's natural size on both axes, even beside tall buttons."""
    control.set_halign(Gtk.Align.END)
    control.set_valign(Gtk.Align.CENTER)
    control.set_hexpand(False)
    control.set_vexpand(False)
    control.get_style_context().add_class('adws-compact-switch')
    return control


def settings_tabs(pages):
    """Named pages with compact navigation; hidden content keeps its state."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    stack = Gtk.Stack()
    stack.set_hhomogeneous(False)
    stack.set_vhomogeneous(False)
    stack.set_transition_type(Gtk.StackTransitionType.NONE)
    switcher = Gtk.StackSwitcher(stack=stack)
    switcher.set_halign(Gtk.Align.START)
    switcher.set_homogeneous(False)
    switcher.get_style_context().add_class('settings-subnav')
    box.pack_start(switcher, False, False, 0)
    box.pack_start(stack, False, False, 0)
    for key, title, page in pages:
        stack.add_titled(page, key, title)
    box.stack = stack
    return box


def enhance_choices(container, translate=lambda text: text):
    """Upgrade safe text choices recursively; repeat calls are idempotent.

    Editable font selectors share the original entry buffer. Gtk.Box and
    Gtk.Grid are supported; unusual custom parents remain untouched. No wheel
    signal is consumed, so scrolling continues to the enclosing settings page
    and cannot change the selected value.
    """
    enhanced = []

    def visit(widget):
        if isinstance(widget, SelectionButton):
            return
        if isinstance(widget, Gtk.Switch):
            compact_switch(widget)
            return
        if isinstance(widget, Gtk.ComboBoxText):
            if not hasattr(widget, "_adws_choice_button"):
                replacement = _insert_choice(widget, translate)
                if replacement is not None:
                    enhanced.append(replacement)
            return
        if isinstance(widget, Gtk.Container):
            for child in list(widget.get_children()):
                visit(child)

    visit(container)
    return enhanced

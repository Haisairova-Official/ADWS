"""Schema-driven settings dialog for ADWS plugins."""
from __future__ import annotations
from adws_i18n import tr as _tr

import string
import urllib.parse

from adws_i18n import prepare_gtk_language
prepare_gtk_language()
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango


def validate_settings(values: dict) -> None:
    if values.get("api_mode") != "custom":
        return
    template = values.get("api_url", "").strip()
    if not template:
        raise ValueError(_tr('选择自定义 API 后，请填写地址。'))
    allowed = {"id", "title", "artist", "album", "duration"}
    for _, field, spec, conversion in string.Formatter().parse(template):
        if field is not None and (field not in allowed or spec or conversion):
            raise ValueError(_tr('地址模板只支持 {id}、{title}、{artist}、{album} 和 {duration}。'))
    parsed = urllib.parse.urlparse(template.format_map(dict.fromkeys(allowed, "test")))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(_tr('API 地址必须是完整的 HTTP 或 HTTPS 地址。'))


class SettingsDialog:
    def __init__(self, parent, name, schema, values, validator=None, animations=None):
        self.schema = schema
        self.animations = animations
        self.validator = validator
        self.values = dict(values)
        self.controls = {}
        self.field_widgets = {}
        self.dialog = Gtk.Dialog(title=name + _tr('设置'), transient_for=parent,
                                 modal=True, destroy_with_parent=True)
        # A desktop layer surface is not an xdg_toplevel transient parent.
        # Fixed min/max size makes this a floating dialog in tiling compositors
        # without installing global compositor rules or changing the desktop.
        self.dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.dialog.set_resizable(False)
        self.dialog.set_default_size(500, min(520, 140 + len(schema) * 46))
        self.dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.dialog.add_button(_tr('取消'), Gtk.ResponseType.CANCEL)
        self.dialog.add_button(_tr('保存并应用'), Gtk.ResponseType.OK)
        self.dialog.set_default_response(Gtk.ResponseType.OK)
        content = self.dialog.get_content_area()
        content.set_border_width(16)
        content.set_spacing(10)
        if animations is not None:
            self.animation_toggle = Gtk.CheckButton(label=_tr('启用动画（淡入淡出与宽度过渡）'))
            self.animation_toggle.set_active(animations)
            self.animation_toggle.set_tooltip_text(_tr('默认关闭。按钮淡入淡出；自适应宽度使用贝塞尔缓动，跟随系统动画设置。'))
            content.pack_start(self.animation_toggle, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content.pack_start(scroll, True, True, 0)
        grid = Gtk.Grid(column_spacing=16, row_spacing=12)
        scroll.add(grid)
        row = 0
        for field in schema:
            key, kind = field["key"], field.get("type", "string")
            value = values.get(key, field.get("default", ""))
            label = Gtk.Label(label=_tr(field.get("label", key)), xalign=0)
            label.set_line_wrap(True)
            label.set_max_width_chars(20)
            grid.attach(label, 0, row, 1, 1)
            if kind in ("font", "color"):
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                follow = Gtk.CheckButton(label=_tr('跟随主题'))
                follow.set_active(not value)
                if kind == "font":
                    control = Gtk.FontButton()
                    control.set_show_size(False)
                    control.set_level(Gtk.FontChooserLevel.FAMILY)
                    if value:
                        control.set_font_name(str(value))
                else:
                    control = Gtk.ColorButton()
                    control.set_use_alpha(True)
                    rgba = Gdk.RGBA()
                    rgba.parse(str(value) if value else "#ffffff")
                    control.set_rgba(rgba)
                control.set_sensitive(bool(value))
                follow.connect("toggled", lambda toggle, target=control: target.set_sensitive(not toggle.get_active()))
                box.pack_start(control, True, True, 0)
                box.pack_start(follow, False, False, 0)
                widget = box
                self.controls[key] = (kind, control, follow)
            elif kind == "boolean":
                control = Gtk.Switch()
                control.set_halign(Gtk.Align.END)
                control.set_valign(Gtk.Align.CENTER)
                control.set_active(bool(value))
                widget = control
                self.controls[key] = (kind, control, None)
            elif kind == "choice":
                control = Gtk.ComboBoxText()
                for choice, caption in field.get("choices", []):
                    control.append(choice, _tr(caption))
                control.set_active_id(str(value))
                widget = control
                self.controls[key] = (kind, control, None)
            elif kind == "number":
                control = Gtk.SpinButton.new_with_range(field.get("min", 0), field.get("max", 100), field.get("step", 1))
                control.set_value(float(value))
                widget = control
                self.controls[key] = (kind, control, None)
            else:
                control = Gtk.Entry()
                control.set_text(str(value))
                control.set_hexpand(True)
                widget = control
                self.controls[key] = (kind, control, None)
                if field.get('chooser') == 'image':
                    widget = Gtk.Box(spacing=6)
                    widget.pack_start(control, True, True, 0)
                    choose = Gtk.Button.new_from_icon_name('document-open-symbolic', Gtk.IconSize.BUTTON)
                    choose.set_tooltip_text(_tr('选择图片'))
                    choose.connect('clicked', lambda _, entry=control: self.choose_image(entry))
                    widget.pack_start(choose, False, False, 0)
            widget.set_hexpand(True)
            grid.attach(widget, 1, row, 1, 1)
            self.field_widgets[key] = [label, widget]
            row += 1
            if field.get("hint"):
                hint = Gtk.Label(label=_tr(field["hint"]), xalign=0)
                hint.set_line_wrap(True)
                hint.set_max_width_chars(44)
                hint.get_style_context().add_class("dim-label")
                grid.attach(hint, 1, row, 1, 1)
                self.field_widgets[key].append(hint)
                row += 1
        for kind, control, _ in self.controls.values():
            if kind == 'choice':control.connect('changed', self.update_visibility)
            elif kind == 'boolean':control.connect('notify::active', self.update_visibility)
        from adws_settings_widgets import enhance_choices
        enhance_choices(self.dialog, translate=_tr)
        self.update_visibility()
        self.error = Gtk.Label(xalign=0)
        self.error.set_line_wrap(True)
        content.pack_start(self.error, False, False, 0)

    def update_visibility(self, *_):
        visible_count=0
        for field in self.schema:
            conditions=field.get('visibleWhen', {})
            visible=True
            if isinstance(conditions,dict):
                for key,expected in conditions.items():
                    control=self.controls.get(key)
                    actual=(control[1].get_active_id() if control[0]=='choice' else control[1].get_active() if control[0]=='boolean' else None) if control else None
                    visible=visible and actual==expected
            visible_count+=int(visible)
            for widget in self.field_widgets[field['key']]:
                adapter=getattr(widget,'_adws_choice_button',None)
                target=adapter.presentation if adapter else widget
                target.set_no_show_all(not visible);target.set_visible(visible)
                if adapter:
                    widget.set_no_show_all(True);widget.hide()
                    if not visible:adapter.set_active(False)
        self.dialog.set_default_size(500,min(520,140+visible_count*46))
        self.dialog.resize(500,min(520,140+visible_count*46))

    def choose_image(self, entry):
        chooser=Gtk.FileChooserDialog(title=_tr('选择图片'),transient_for=self.dialog,modal=True,action=Gtk.FileChooserAction.OPEN)
        chooser.set_resizable(False);chooser.set_default_size(640,440)
        chooser.add_buttons(_tr('取消'),Gtk.ResponseType.CANCEL,_tr('打开'),Gtk.ResponseType.OK)
        image_filter=Gtk.FileFilter();image_filter.set_name(_tr('图片'));image_filter.add_pixbuf_formats();chooser.add_filter(image_filter)
        try:
            if chooser.run()==Gtk.ResponseType.OK and chooser.get_filename():entry.set_text(chooser.get_filename())
        finally:chooser.destroy()

    def collect(self):
        if self.animations is not None:
            self.animations = self.animation_toggle.get_active()
        result = dict(self.values)
        for key, (kind, control, follow) in self.controls.items():
            if follow is not None and follow.get_active():
                result[key] = ""
            elif kind == "font":
                result[key] = Pango.FontDescription.from_string(control.get_font_name()).get_family()
            elif kind == "color":
                result[key] = control.get_rgba().to_string()
            elif kind == "choice":
                result[key] = control.get_active_id()
            elif kind == "boolean":
                result[key] = control.get_active()
            elif kind == "number":
                result[key] = control.get_value()
            else:
                result[key] = control.get_text().strip()
        from pathlib import Path
        for field in self.schema:
            value=result.get(field['key'])
            if field.get('chooser')=='image' and value:
                path=Path(value).expanduser()
                try:
                    if not path.is_file() or path.stat().st_size>32*1024*1024:raise OSError()
                    with path.open('rb') as stream:stream.read(1)
                except OSError:raise ValueError(_tr('请选择可读取且小于 32 MiB 的本地图片。'))
                result[field['key']]=str(path.resolve())
        from adws_plugin_api import settings
        result = settings({'settingsSchema': self.schema}, result)
        if self.validator is not None:
            self.validator(result)
        return result

    def run(self):
        self.dialog.show_all()
        self.update_visibility()
        while self.dialog.run() == Gtk.ResponseType.OK:
            try:
                result = self.collect()
            except ValueError as error:
                self.error.set_text(str(error))
                continue
            self.dialog.destroy()
            return result
        self.dialog.destroy()
        return None

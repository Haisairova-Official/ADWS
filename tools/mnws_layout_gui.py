#!/usr/bin/env python3
"""mnws-layout GUI — 任务栏组件与插件管理窗口（由 mnws layout gui 调用）"""
from __future__ import annotations
from mnws_i18n import tr as _tr

import json
from pathlib import Path

from mnws_layout import (BUILTIN_INFO, PROJECT_LAYOUT_PATH,
                         load_layout, normalize_plugin_defaults, plugin_dir,
                         save_layout, scan_available_plugins, layout_path,
                         apply_layout)
import mnws_layout
import mnws_plugin as mplg
from mnws_launcher import rofi_theme_command

SLOT_ORDER = {"left": 0, "center": 1, "right": 2}


def _gtk():
    from mnws_i18n import prepare_gtk_language
    prepare_gtk_language()
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
    return Gdk, Gtk


class LayoutWindow:
    """任务栏组件与插件布局窗口（内置组件 + .mplg 插件）。"""

    def __init__(self, layout_file=None, open_plugin=None, parent=None, on_apply=None):
        Gdk, Gtk = _gtk()
        from mnws_theme import start as start_theme_watch
        start_theme_watch()
        self.Gtk = Gtk
        self.layout_file = Path(layout_file) if layout_file else None
        self.rows = []
        self.embedded = parent is not None
        self.on_apply = on_apply

        self.window = parent if self.embedded else Gtk.Window(title=_tr('任务栏组件与插件 — MNWS'))
        if not self.embedded:
            self.window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            self.window.set_default_size(820, 620)
            self.window.set_border_width(12)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.content = outer
        if not self.embedded:
            self.window.add(outer)

        heading = Gtk.Label(label=_tr('任务栏布局'), xalign=0)
        heading.get_style_context().add_class("title")
        outer.pack_start(heading, False, False, 0)

        sub = Gtk.Label(
            label=_tr('内置组件（开始按钮 / 工作区 / 窗口图标 / 时钟）与 .mplg 插件都按“位置 + 顺序”独立加载。\n.mplg 直接丢进插件目录即可被发现，这里负责开关、排序与宽度。'),
            xalign=0,
        )
        sub.get_style_context().add_class("dim-label")
        sub.set_line_wrap(True)
        outer.pack_start(sub, False, False, 0)

        icon_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon_row.pack_start(Gtk.Label(label=_tr('开始按钮图标 / 文字：')), False, False, 0)
        self.start_mode = Gtk.ComboBoxText()
        self.start_mode.append("custom", _tr('自定义图标 / 文字'))
        self.start_mode.append("distro", _tr('系统发行版 Logo'))
        self.start_mode.append("image", _tr('图片'))
        icon_row.pack_start(self.start_mode, False, False, 0)
        self.start_label = Gtk.Entry()
        self.start_label.set_placeholder_text(_tr('例如：开始、Apps、☰、🚀；留空恢复默认'))
        icon_row.pack_start(self.start_label, True, True, 0)
        outer.pack_start(icon_row, False, False, 0)
        self.start_preview = Gtk.Label(xalign=0)
        outer.pack_start(self.start_preview, False, False, 0)
        self.start_mode.connect("changed", lambda *_: self.update_start_preview())
        self.start_label.connect("changed", lambda *_: self.update_start_preview())
        self.image_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.image_box.set_no_show_all(True)
        self.start_images = {}
        for key, caption in [("start_image", _tr('默认图片')), ("start_hover_image", _tr('悬停图片（可选）'))]:
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Label(label=caption), False, False, 0)
            entry = Gtk.Entry()
            entry.set_hexpand(True)
            entry.connect("changed", lambda *_: self.check_start_images())
            self.start_images[key] = entry
            row.pack_start(entry, True, True, 0)
            choose = Gtk.Button(label=_tr('选择图片…'))
            choose.connect("clicked", self.choose_start_image, key)
            row.pack_start(choose, False, False, 0)
            self.image_box.pack_start(row, False, False, 0)
        self.image_error = Gtk.Label(xalign=0)
        self.image_error.set_line_wrap(True)
        self.image_box.pack_start(self.image_error, False, False, 0)
        outer.pack_start(self.image_box, False, False, 0)

        launcher_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        launcher_row.pack_start(Gtk.Label(label=_tr('开始按钮启动器：')), False, False, 0)
        self.launcher_mode = Gtk.ComboBoxText()
        self.launcher_mode.append("fuzzel", "fuzzel")
        self.launcher_mode.append("rofi", "rofi (-show drun)")
        self.launcher_mode.append("custom", _tr('自定义命令'))
        launcher_row.pack_start(self.launcher_mode, False, False, 0)
        self.launcher_command = Gtk.Entry()
        self.launcher_command.set_placeholder_text(_tr('输入启动器命令及参数，例如：wofi --show drun'))
        launcher_row.pack_start(self.launcher_command, True, True, 0)
        self.rofi_themed = False
        self.rofi_theme_button = Gtk.Button(label=_tr('设置 rofi 为 MNWS 主题'))
        self.rofi_theme_button.set_no_show_all(True)
        self.rofi_theme_button.connect("clicked", self.on_rofi_theme)
        launcher_row.pack_start(self.rofi_theme_button, False, False, 0)
        self.launcher_mode.connect("changed", self.update_launcher_controls)
        outer.pack_start(launcher_row, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_btn = Gtk.Button(label=_tr('添加 .mplg…'))
        add_btn.connect("clicked", self.on_add_plugin)
        refresh_btn = Gtk.Button(label=_tr('刷新'))
        refresh_btn.connect("clicked", lambda _b: self.reload())
        reset_btn = Gtk.Button(label=_tr('恢复默认布局'))
        reset_btn.connect("clicked", self.on_reset)
        open_dir_btn = Gtk.Button(label=_tr('打开插件目录'))
        open_dir_btn.connect("clicked", self.on_open_plugin_dir)
        toolbar.pack_start(add_btn, False, False, 0)
        toolbar.pack_start(refresh_btn, False, False, 0)
        toolbar.pack_start(reset_btn, False, False, 0)
        toolbar.pack_start(open_dir_btn, False, False, 0)
        outer.pack_start(toolbar, False, False, 0)

        self.status = Gtk.Label(label="", xalign=0)
        self.status.get_style_context().add_class("dim-label")
        self.status.set_line_wrap(True)
        outer.pack_start(self.status, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroller.add(self.list_box)
        outer.pack_start(scroller, True, True, 0)

        if not self.embedded:
            footer = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
            footer.set_halign(Gtk.Align.END)
            save_btn = Gtk.Button(label=_tr('保存布局'))
            save_btn.connect("clicked", lambda _b: self.save_layout(restart=False))
            apply_btn = Gtk.Button(label=_tr('应用并重启任务栏'))
            apply_btn.connect("clicked", lambda _b: self.save_layout(restart=True))
            close_btn = Gtk.Button(label=_tr('关闭'))
            close_btn.connect("clicked", lambda _b: self.window.destroy())
            footer.pack_end(close_btn, False, False, 0)
            footer.pack_end(apply_btn, False, False, 0)
            footer.pack_end(save_btn, False, False, 0)
            outer.pack_end(footer, False, False, 0)
            self.window.connect("destroy", Gtk.main_quit)
        self.reload()
        if not self.embedded:
            self.window.show_all()
        if open_plugin:
            from gi.repository import GLib
            GLib.idle_add(self.open_plugin_settings, open_plugin)

    # ---------- 行构建 ----------

    def _clear_rows(self):
        for child in self.list_box.get_children():
            self.list_box.remove(child)
        self.rows = []

    def _add_row(self, entry):
        Gtk = self.Gtk
        from gi.repository import Pango
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_bottom(2)

        switch = Gtk.Switch()
        switch.set_active(bool(entry.get("enabled", False)))
        switch.set_valign(Gtk.Align.CENTER)
        box.pack_start(switch, False, False, 0)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name_label = Gtk.Label(label=entry["name"], xalign=0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.set_width_chars(1)
        name_label.set_max_width_chars(1)
        name_label.set_tooltip_text(entry["name"])
        name_label.get_style_context().add_class("title")
        subtitle = entry.get("subtitle") or ""
        if subtitle:
            sub_label = Gtk.Label(label=subtitle, xalign=0)
            sub_label.set_ellipsize(Pango.EllipsizeMode.END)
            sub_label.set_width_chars(1)
            sub_label.set_max_width_chars(1)
            sub_label.set_tooltip_text(subtitle)
            sub_label.get_style_context().add_class("dim-label")
            label_box.pack_start(sub_label, False, False, 0)
        label_box.pack_start(name_label, False, False, 0)
        label_box.set_hexpand(True)
        box.pack_start(label_box, True, True, 0)

        slot_combo = Gtk.ComboBoxText()
        for value, label in (("left", _tr('前部')), ("center", _tr('中间')), ("right", _tr('后部'))):
            slot_combo.append(value, label)
        slot_combo.set_active_id(entry.get("slot", "left"))
        slot_combo.connect("changed", lambda combo, e=entry: self.change_slot(e, combo.get_active_id()))
        box.pack_start(slot_combo, False, False, 0)

        width_spin = Gtk.SpinButton.new_with_range(0, 512, 4)
        width_spin.set_digits(0)
        width_spin.set_value(float(entry.get("width", 0) or 0))
        width_spin.set_tooltip_text(_tr('像素宽度；0 = 随文字长度变化'))
        width_spin.set_sensitive(bool(entry.get("editable_width", False)))
        box.pack_start(width_spin, False, False, 0)

        up = Gtk.Button(label="↑")
        up.set_tooltip_text(_tr('上移'))
        up.connect("clicked", lambda _b, e=entry: self.move_row(e, -1))
        down = Gtk.Button(label="↓")
        down.set_tooltip_text(_tr('下移'))
        down.connect("clicked", lambda _b, e=entry: self.move_row(e, 1))
        box.pack_start(up, False, False, 0)
        box.pack_start(down, False, False, 0)

        if entry.get("kind") == "plugin":
            if entry.get("manifest", {}).get("settingsSchema") or "panel.rows-v1" in entry.get("manifest", {}).get("interfaces", []):
                settings_btn = Gtk.Button(label=_tr('设置…'))
                settings_btn.connect("clicked", lambda _b, e=entry: self.on_plugin_settings(e))
                box.pack_start(settings_btn, False, False, 0)
            remove_btn = Gtk.Button(label=_tr('移除'))
            remove_btn.connect("clicked", lambda _b, e=entry: self.on_remove_plugin(e))
            box.pack_start(remove_btn, False, False, 0)

        entry["widgets"] = {"switch": switch, "slot": slot_combo, "width": width_spin}
        entry["box"] = box
        self.rows.append(entry)
        self.list_box.pack_start(box, False, False, 0)
        if self.embedded and hasattr(self, "protect_scroll"):
            self.protect_scroll(box)

    def reload(self, layout=None):
        self._clear_rows()
        if layout is None:
            layout = load_layout(self.layout_file)
        options = layout.get("options", {})
        try:
            definition = mnws_layout.launcher_definition()
        except (OSError, ValueError):
            definition = {}
        current = definition.get("format", _tr('开始'))
        command = options.get("start_launcher_command", definition.get("on-click", "fuzzel"))
        command = command if isinstance(command, str) and command.strip() else "fuzzel"
        self.rofi_themed = command.strip() == rofi_theme_command()
        mode = {"fuzzel": "fuzzel", "rofi -show drun": "rofi",
                rofi_theme_command(): "rofi"}.get(command.strip(), "custom")
        self.launcher_command.set_text(options.get("start_launcher_custom", command if mode == "custom" else ""))
        self.launcher_mode.set_active_id(mode)
        self.update_launcher_controls()
        import html
        current = html.unescape(str(current)).replace("{{", "{").replace("}}", "}")
        self.start_label.set_text(options.get("start_label") or current)
        for key, entry in self.start_images.items():
            entry.set_text(str(options.get(key) or ""))
        self.start_mode.set_active_id(options.get("start_icon_mode", "custom"))
        self.update_start_preview()
        available = {item["manifest"]["id"]: item
                     for item in scan_available_plugins() if item.get("ok")}

        stored_builtins = {
            item.get("id"): item for item in layout.get("builtins", [])
            if isinstance(item, dict) and item.get("id")
        }
        builtin_rows = []
        for builtin_id, info in BUILTIN_INFO.items():
            stored = stored_builtins.get(builtin_id, {})
            builtin_rows.append({
                "kind": "builtin",
                "key": builtin_id,
                "name": info["name"],
                "subtitle": _tr('内置 · %s') % info["module"],
                "enabled": bool(stored.get("enabled",
                                           builtin_id in ("start", "windows", "clock"))),
                "slot": stored.get("slot", info["slot"]) or info["slot"],
                "order": int(stored.get("order", 0) or 0),
                "width": 0,
                "editable_width": False,
            })
        stored_plugins = {
            item.get("package"): item for item in layout.get("plugins", [])
            if isinstance(item, dict) and item.get("package")
        }
        plugin_rows = []
        package_ids = list(stored_plugins) + sorted(set(available) - set(stored_plugins))
        for package_id in package_ids:
            entry = available.get(package_id)
            if entry is None:
                continue
            manifest = entry["manifest"]
            stored = stored_plugins.get(package_id, {})
            defaults = normalize_plugin_defaults(manifest)
            width = stored.get("width", defaults["width"])
            if width is None:
                width = defaults["width"]
            plugin_rows.append({
                "kind": "plugin",
                "key": package_id,
                "name": _tr(manifest.get("name", package_id)),
                "subtitle": _tr('插件 · %s v%s · %s') % (
                    package_id, manifest.get("version", "?"), entry["file"].name),
                "enabled": bool(stored.get("enabled", False)),
                "slot": stored.get("slot", defaults["slot"]) or defaults["slot"],
                "order": int(stored.get("order", 0) or 0),
                "width": max(0, int(width or 0)),
                "animations": stored.get("animations") is True,
                "editable_width": True,
                "file": entry["file"],
                "manifest": manifest,
                "settings": dict(stored.get("settings") or {}),
            })
        # Builtins and plugins share the same slot/order namespace in Waybar.
        # Sorting separately changes their relative order on every load/save.
        rows = sorted(builtin_rows + plugin_rows,
                      key=lambda item: (SLOT_ORDER.get(item["slot"], 0), item["order"]))
        for entry in rows:
            self._add_row(entry)
        if not self.rows:
            hint = Gtk.Label(
                label=_tr('还没有 .mplg。点击“添加 .mplg…”选择一个，或把文件直接丢进\n%s')
                      % plugin_dir(),
                xalign=0,
            )
            hint.get_style_context().add_class("dim-label")
            hint.set_line_wrap(True)
            hint.set_margin_top(12)
            self.list_box.pack_start(hint, False, False, 0)
        self.update_status(layout)
        self.list_box.show_all()

    def update_status(self, _layout=None):
        target = self.layout_file or layout_path()
        self.status.set_text(_tr('布局：%s\n插件目录：%s') % (target, plugin_dir()))

    # ---------- 排序 / 增删 ----------

    def change_slot(self, entry, slot):
        if entry not in self.rows or slot not in SLOT_ORDER or entry.get("slot") == slot:
            return
        self.rows.remove(entry)
        entry["slot"] = slot
        # Moving to a different section appends within that section only.
        index = next((i for i, row in enumerate(self.rows)
                      if SLOT_ORDER.get(row["slot"], 0) > SLOT_ORDER[slot]), len(self.rows))
        self.rows.insert(index, entry)
        for i, row in enumerate(self.rows):
            self.list_box.reorder_child(row["box"], i)

    def move_row(self, entry, delta):
        index = self.rows.index(entry)
        other = index + delta
        if other < 0 or other >= len(self.rows):
            return
        if self.rows[other].get("slot") != entry.get("slot"):
            return
        self.rows[index], self.rows[other] = self.rows[other], self.rows[index]
        self.list_box.reorder_child(entry["box"], other)

    def on_open_plugin_dir(self, _button=None):
        folder = plugin_dir()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            import subprocess
            subprocess.Popen(["xdg-open", str(folder)], start_new_session=True)
        except OSError as exc:
            self.show_message(_tr('无法打开目录'), str(exc))

    def on_add_plugin(self, _button=None):
        Gtk = self.Gtk
        dialog = Gtk.FileChooserDialog(
            title=_tr('添加 .mplg 插件'), transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        filtr = Gtk.FileFilter()
        filtr.set_name(_tr('.mplg 插件包'))
        filtr.add_pattern("*.mplg")
        dialog.add_filter(filtr)
        if dialog.run() == Gtk.ResponseType.OK:
            path = Path(dialog.get_filename())
            dialog.destroy()
            ok, errors, _ = mplg.validate_package(path)
            if not ok:
                self.show_message(_tr('无法添加'), "；".join(errors))
                return
            try:
                mplg.copy_into(plugin_dir(), path)
            except OSError as exc:
                self.show_message(_tr('无法添加'), str(exc))
                return
            self.reload()
        else:
            dialog.destroy()

    def on_remove_plugin(self, entry):
        if not entry.get("file") or not entry["file"].is_file():
            self.reload()
            return
        Gtk = self.Gtk
        confirm = Gtk.MessageDialog(
            transient_for=self.window, modal=True, destroy_with_parent=True,
            message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO,
            text=_tr('移除插件？'),
        )
        confirm.format_secondary_text(
            _tr('将删除扫描目录中的文件：\n%s\n\n若已应用到任务栏，需要重新应用布局。') % entry["file"])
        if confirm.run() == Gtk.ResponseType.YES:
            confirm.destroy()
            try:
                entry["file"].unlink()
            except OSError as exc:
                self.show_message(_tr('删除失败'), str(exc))
                return
            self.reload()
        else:
            confirm.destroy()

    def on_reset(self, _button=None):
        Gtk = self.Gtk
        confirm = Gtk.MessageDialog(
            transient_for=self.window, modal=True, destroy_with_parent=True,
            message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO,
            text=_tr('恢复默认布局？'),
        )
        confirm.format_secondary_text(
            _tr('内置组件回到默认启用状态，已安装插件会保留但全部关闭。'))
        if confirm.run() != Gtk.ResponseType.YES:
            confirm.destroy()
            return
        confirm.destroy()
        try:
            defaults = json.loads(PROJECT_LAYOUT_PATH.read_text(encoding="utf-8"))
            if self.embedded:
                self.reload(defaults)
                self.status.set_text(_tr('布局已恢复默认，点击应用后生效。'))
                return
            save_layout(defaults, self.layout_file)
        except (OSError, ValueError) as exc:
            self.show_message(_tr('恢复失败'), str(exc))
            return
        self.reload()

    def on_plugin_settings(self, entry):
        from mnws_plugin_settings import SettingsDialog, validate_settings
        from mnws_plugin_api import canonical_id
        dialog = SettingsDialog(self.window, entry["name"],
                                entry["manifest"].get("settingsSchema", []),
                                entry.get("settings", {}),
                                animations=entry.get("animations", False) if "panel.rows-v1" in entry["manifest"].get("interfaces", []) else None,
                                validator=validate_settings if canonical_id(entry['manifest']['id']) == 'org.AkiACG_Community.NCMLyricsBar' else None)
        values = dialog.run()
        if values is not None:
            entry["settings"] = values
            if dialog.animations is not None:
                entry["animations"] = dialog.animations
            self.save_layout(restart=True)

    def open_plugin_settings(self, package_id):
        from mnws_plugin_api import canonical_id
        package_id = canonical_id(package_id)
        entry = next((row for row in self.rows
                      if row.get("kind") == "plugin" and row.get("key") == package_id), None)
        if entry is None:
            self.show_message(_tr('无法打开插件设置'), _tr('没有找到插件：%s') % package_id, error=True)
        elif not entry.get("manifest", {}).get("settingsSchema") and "panel.rows-v1" not in entry.get("manifest", {}).get("interfaces", []):
            self.show_message(_tr('无法打开插件设置'), _tr('此插件没有可配置的设置。'))
        else:
            self.on_plugin_settings(entry)
        return False

    # ---------- 保存 ----------

    def update_launcher_controls(self, *_):
        mode = self.launcher_mode.get_active_id()
        self.launcher_command.set_sensitive(mode == "custom")
        self.rofi_theme_button.set_visible(mode == "rofi")

    def on_rofi_theme(self, *_):
        self.rofi_themed = True
        self.status.set_text(_tr('已设置 MNWS rofi 主题，点击“应用并重启任务栏”生效。'))

    def update_start_preview(self):
        distro = self.start_mode.get_active_id() == "distro"
        image = self.start_mode.get_active_id() == "image"
        self.start_label.set_sensitive(not distro and not image)
        if hasattr(self, "image_box"):
            if image:
                self.image_box.show()
                for child in self.image_box.get_children():
                    child.show_all()
            else:
                self.image_box.hide()
            self.check_start_images()
        if distro:
            name, glyph = mnws_layout.distro_logo()
            self.start_preview.set_text(''.join([_tr('预览：'), f'{glyph}', '  · ', f'{name}', _tr('（需 Nerd Fonts / Font Logos 字体支持）')]))
        else:
            self.start_preview.set_text(_tr('预览：') + (self.start_label.get_text() or _tr('开始')))

    def image_options(self):
        return {"start_icon_mode": self.start_mode.get_active_id(),
                **{key: entry.get_text().strip() for key, entry in self.start_images.items()}}

    def check_start_images(self):
        if not hasattr(self, "image_error"):
            return
        from gi.repository import GLib
        try:
            mnws_layout.validate_start_images(self.image_options())
        except ValueError as exc:
            self.image_error.set_markup('<span foreground="#e53935">' + GLib.markup_escape_text(str(exc)) + '</span>')
        else:
            self.image_error.set_text("")

    def choose_start_image(self, _button, key):
        Gtk = self.Gtk
        dialog = Gtk.FileChooserDialog(title=_tr('选择图片…'), transient_for=self.window,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(_tr('取消'), Gtk.ResponseType.CANCEL, _tr('确定'), Gtk.ResponseType.OK)
        images = Gtk.FileFilter()
        images.set_name(_tr('图片'))
        images.add_pixbuf_formats()
        dialog.add_filter(images)
        if dialog.run() == Gtk.ResponseType.OK:
            self.start_images[key].set_text(dialog.get_filename())
        dialog.destroy()
        if self.image_error.get_text():
            self.show_message(_tr('图片错误'), self.image_error.get_text(), error=True)

    def collect_layout(self) -> dict:
        layout = load_layout(self.layout_file)
        builtins, plugins = [], []
        for row in self.rows:
            widgets = row["widgets"]
            enabled = bool(widgets["switch"].get_active())
            slot = widgets["slot"].get_active_id() or "left"
            if row["kind"] == "builtin":
                builtins.append({
                    "id": row["key"], "enabled": enabled, "slot": slot, "order": 0,
                })
            else:
                plugins.append({
                    "package": row["key"], "enabled": enabled, "slot": slot,
                    "order": 0,
                    "width": int(widgets["width"].get_value()),
                    "animations": row.get("animations") is True,
                    "settings": dict(row.get("settings") or {}),
                })
        counters = {"left": 0, "center": 0, "right": 0}
        for row in self.rows:
            slot = row["widgets"]["slot"].get_active_id() or "left"
            row["slot"] = slot
            row["order"] = counters[slot]
            counters[slot] += 1
        for item in builtins:
            row = next(row for row in self.rows
                       if row["kind"] == "builtin" and row["key"] == item["id"])
            item["order"] = row["order"]
        for item in plugins:
            row = next(row for row in self.rows
                       if row["kind"] == "plugin" and row["key"] == item["package"])
            item["order"] = row["order"]
        # Applying appearance settings also collects this page. Preserve settings
        # for packages temporarily unavailable instead of silently deleting them.
        visible_builtins = {row["key"] for row in self.rows if row["kind"] == "builtin"}
        visible_plugins = {row["key"] for row in self.rows if row["kind"] == "plugin"}
        builtins.extend(item for item in layout.get("builtins", [])
                        if item.get("id") not in visible_builtins)
        plugins.extend(item for item in layout.get("plugins", [])
                       if item.get("package") not in visible_plugins)
        layout["builtins"] = builtins
        layout["plugins"] = plugins
        layout.setdefault("options", {})["start_label"] = self.start_label.get_text().strip()
        layout["options"]["start_icon_mode"] = self.start_mode.get_active_id() or "custom"
        images = self.image_options()
        mnws_layout.validate_start_images(images)
        layout["options"].update(images)
        custom = self.launcher_command.get_text().strip()
        command = {"fuzzel": "fuzzel", "rofi": rofi_theme_command() if self.rofi_themed else "rofi -show drun"}.get(
            self.launcher_mode.get_active_id(), custom)
        if not command or "\x00" in command:
            raise ValueError(_tr('请输入启动器命令。'))
        layout["options"]["start_launcher_command"] = command
        layout["options"]["start_launcher_custom"] = custom
        layout["apiVersion"] = 1
        return layout

    def save_layout(self, restart: bool, _button=None):
        if self.embedded and self.on_apply is not None:
            return self.on_apply()
        try:
            layout = self.collect_layout()
            path = save_layout(layout, self.layout_file)
        except (OSError, ValueError) as exc:
            self.show_message(_tr('保存失败'), str(exc), error=True)
            return False
        text = _tr('已保存布局：%s') % path
        if restart:
            ok, result = apply_layout(layout, restart=True)
            if not ok:
                self.show_message(_tr('应用失败'), result)
                return False
            text += "\n" + result
        self.status.set_text(_tr('%s\n插件目录：%s') % (text, plugin_dir()))
        return True

    def show_message(self, title, message, error=False):
        Gtk = self.Gtk
        dialog = Gtk.MessageDialog(
            transient_for=self.window, modal=True, destroy_with_parent=True,
            message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        if error:
            from gi.repository import GLib
            dialog.format_secondary_markup('<span foreground="#e53935">' + GLib.markup_escape_text(message) + '</span>')
        else:
            dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


def run(layout_file=None, open_plugin=None) -> int:
    from gi.repository import GLib
    # Wayland's app_id comes from prgname, not the X11 program class.
    GLib.set_prgname("mnws-layout")
    Gdk, Gtk = _gtk()
    Gdk.set_program_class("mnws-layout")
    import importlib.util
    spec = importlib.util.spec_from_file_location("mnws_config", Path(__file__).with_name("mnws-config.py"))
    settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings)
    settings.TaskbarSettingsWindow(tab="layout", layout_file=layout_file, open_plugin=open_plugin)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

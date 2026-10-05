#!/usr/bin/env python3
"""adws-layout GUI — 任务栏组件与插件管理窗口（由 adws layout gui 调用）"""
from __future__ import annotations
from adws_i18n import tr as _tr

import json
import copy
from pathlib import Path

from adws_layout import (BUILTIN_INFO, PROJECT_LAYOUT_PATH,
                         load_layout, normalize_plugin_defaults, plugin_dir,
                         save_layout, scan_available_plugins, layout_path,
                         apply_layout)
import adws_layout
import adws_plugin as mplg
from adws_launcher import rofi_theme_command, native_menu_command

SLOT_ORDER = {"left": 0, "center": 1, "right": 2}


def _gtk():
    from adws_i18n import prepare_gtk_language
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
        from adws_theme import start as start_theme_watch
        start_theme_watch()
        self.Gtk, self.Gdk = Gtk, Gdk
        self.layout_file = Path(layout_file) if layout_file else None
        self.rows = []
        self.embedded = parent is not None
        self.on_apply = on_apply
        self.on_start_settings = None
        self.on_changed = None
        self.selected_entry = None
        self.start_instance = "start"
        self.loading = True
        self.preview_source = 0
        self.closed = False
        self.get_preview_options = None

        self.window = parent if self.embedded else Gtk.Window(title=_tr('任务栏组件与插件 — ADWS'))
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
        if not self.embedded:
            outer.pack_start(heading, False, False, 0)

        sub = Gtk.Label(
            label=_tr('从上方添加组件，选中卡片后调整位置与设置。开始按钮和时钟支持多个实例。'),
            xalign=0,
        )
        sub.get_style_context().add_class("dim-label")
        sub.set_line_wrap(True)
        outer.pack_start(sub, False, False, 0)

        self.start_settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.start_settings.set_border_width(18)
        heading = Gtk.Label(label=_tr('开始菜单与按钮'), xalign=0)
        heading.get_style_context().add_class('title')
        self.start_settings.pack_start(heading, False, False, 0)
        hint = Gtk.Label(label=_tr('关闭任务栏开始按钮后，仍可在这里设置、预览菜单，或使用 adws start-menu 打开。'), xalign=0)
        hint.set_line_wrap(True)
        self.start_settings.pack_start(hint, False, False, 0)
        self.start_enabled = Gtk.CheckButton(label=_tr('在任务栏显示开始按钮'))
        self.start_settings.pack_start(self.start_enabled, False, False, 0)
        self.start_instance_choice = Gtk.ComboBoxText()
        self.start_instance_choice.connect('changed', self.change_start_instance)
        instance_row = Gtk.Box(spacing=8)
        instance_row.pack_start(Gtk.Label(label=_tr('开始按钮实例'), xalign=0), False, False, 0)
        instance_row.pack_start(self.start_instance_choice, True, True, 0)
        self.start_settings.pack_start(instance_row, False, False, 0)
        self.start_enabled.connect('toggled', self.toggle_start_instance)

        keys_row = Gtk.Box(spacing=8)
        keys_row.pack_start(Gtk.Label(label=_tr('快捷键位'), xalign=0), False, False, 0)
        self.keyboard_profile = Gtk.ComboBoxText()
        for key, label in [('waylander', 'Waylander：Super 全览 / Ctrl 无动作'),
                           ('traditional', 'Traditional：Super 开始 / Ctrl 全览'),
                           ('reversed', 'Reversed：Ctrl 开始 / Super 全览')]:
            self.keyboard_profile.append(key, key.capitalize() if key != "waylander" else "Waylander")
        from adws_keyboard import current_profile, modifier_taps_supported
        try:
            self.keyboard_profile.set_active_id(current_profile())
        except OSError:
            self.keyboard_profile.set_active_id('waylander')
        taps_supported = modifier_taps_supported()
        self.keyboard_profile.set_sensitive(taps_supported)
        keys_row.pack_start(self.keyboard_profile, True, True, 0)
        keys_apply = Gtk.Button(label=_tr('应用键位方案'))
        keys_apply.connect('clicked', self.apply_keyboard_profile)
        keys_apply.set_sensitive(taps_supported)
        keys_row.pack_start(keys_apply, False, False, 0)
        self.start_settings.pack_start(keys_row, False, False, 0)
        keys_description = Gtk.Label(xalign=0)
        keys_description.set_line_wrap(True)
        def describe_keys(*_args):
            labels = {'waylander': 'Waylander：Super 全览 / Ctrl 无动作',
                      'traditional': 'Traditional：Super 开始 / Ctrl 全览',
                      'reversed': 'Reversed：Ctrl 开始 / Super 全览'}
            keys_description.set_text(_tr(labels[self.keyboard_profile.get_active_id() or 'waylander']))
        self.keyboard_profile.connect('changed', describe_keys)
        describe_keys()
        self.start_settings.pack_start(keys_description, False, False, 0)
        keys_hint = Gtk.Label(label=_tr('单独轻按并松开生效，组合键不变。独立应用到 Niri；开始动作打开 ADWS 菜单。' if taps_supported else '当前 Niri 不支持单修饰键方案，已保留原配置。开始菜单仍可使用普通组合键启动。'), xalign=0)
        keys_hint.set_line_wrap(True)
        keys_hint.get_style_context().add_class('dim-label')
        self.start_settings.pack_start(keys_hint, False, False, 0)
        if not taps_supported:
            compat_hint = Gtk.Label(label=_tr('可选兼容补丁：在终端运行 adws niri-compat build。系统 Niri 不会被替换。'), xalign=0)
            compat_hint.set_line_wrap(True)
            compat_hint.set_selectable(True)
            self.start_settings.pack_start(compat_hint, False, False, 0)
        if not self.embedded:
            outer.pack_start(self.start_settings, False, False, 0)

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
        self.start_settings.pack_start(icon_row, False, False, 0)
        self.start_preview = Gtk.Label(xalign=0)
        self.start_settings.pack_start(self.start_preview, False, False, 0)
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
        self.start_settings.pack_start(self.image_box, False, False, 0)

        launcher_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        launcher_row.pack_start(Gtk.Label(label=_tr('开始按钮启动器：')), False, False, 0)
        self.launcher_mode = Gtk.ComboBoxText()
        self.launcher_mode.append("adws", _tr('ADWS 开始菜单'))
        self.launcher_mode.append("fuzzel", "fuzzel")
        self.launcher_mode.append("rofi", "rofi (-show drun)")
        self.launcher_mode.append("custom", _tr('自定义命令'))
        launcher_row.pack_start(self.launcher_mode, False, False, 0)
        self.launcher_command = Gtk.Entry()
        self.launcher_command.set_placeholder_text(_tr('输入启动器命令及参数，例如：wofi --show drun'))
        launcher_row.pack_start(self.launcher_command, True, True, 0)
        self.rofi_themed = False
        self.rofi_theme_button = Gtk.Button(label=_tr('设置 rofi 为 ADWS 主题'))
        self.rofi_theme_button.set_no_show_all(True)
        self.rofi_theme_button.connect("clicked", self.on_rofi_theme)
        launcher_row.pack_start(self.rofi_theme_button, False, False, 0)
        self.launcher_mode.connect("changed", self.update_launcher_controls)
        self.start_settings.pack_start(launcher_row, False, False, 0)

        right_row = Gtk.Box(spacing=8)
        right_row.pack_start(Gtk.Label(label=_tr('开始按钮右键：')), False, False, 0)
        self.start_right_mode = Gtk.ComboBoxText()
        for key, caption in [('settings', '设置'), ('menu', '菜单'), ('terminal', '默认终端'),
                             ('custom', '自定义命令'), ('none', '留空')]:
            self.start_right_mode.append(key, _tr(caption))
        right_row.pack_start(self.start_right_mode, False, False, 0)
        self.start_right_custom = Gtk.Entry()
        self.start_right_custom.set_placeholder_text(_tr('输入右键自定义命令及参数'))
        self.start_right_custom.set_no_show_all(True)
        right_row.pack_start(self.start_right_custom, True, True, 0)
        self.start_right_mode.connect('changed', self.update_start_right_controls)
        self.start_settings.pack_start(right_row, False, False, 0)
        hint = Gtk.Label(label=_tr('菜单使用所选启动器；留空表示右键不执行操作。'), xalign=0)
        hint.get_style_context().add_class('dim-label')
        hint.set_line_wrap(True)
        self.start_settings.pack_start(hint, False, False, 0)

        self.menu_options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.menu_options.pack_start(Gtk.Label(label=_tr('开始菜单主题：')), False, False, 0)
        self.menu_theme = Gtk.ComboBoxText()
        for key, caption in [('kde', _tr('KDE 风格')), ('aero', _tr('Vista Aero 风格')), ('xp', _tr('Windows XP 风格')), ('akiacg', _tr('AkiACG 星轨'))]:
            self.menu_theme.append(key, caption)
        self.menu_options.pack_start(self.menu_theme, False, False, 0)
        self.menu_css = Gtk.Entry()
        self.menu_css.set_placeholder_text(_tr('自定义 CSS 路径（可留空）'))
        self.menu_options.pack_start(self.menu_css, True, True, 0)
        preview = Gtk.Button(label=_tr('预览菜单'))
        preview.connect('clicked', self.preview_start_menu)
        self.menu_options.pack_start(preview, False, False, 0)
        self.start_settings.pack_start(self.menu_options, False, False, 0)

        toolbar = Gtk.Box(spacing=8)
        self.add_button = Gtk.MenuButton(label=_tr('添加组件'))
        self.add_button.get_style_context().add_class('suggested-action')
        self.add_popover = Gtk.Popover.new(self.add_button)
        self.add_popover.set_no_show_all(True)
        self.add_popover.get_style_context().add_class('adws-settings-popover')
        self.add_button.set_popover(self.add_popover)
        self.add_catalog = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        catalog_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.catalog_search = Gtk.SearchEntry()
        self.catalog_search.set_placeholder_text(_tr('搜索组件…'))
        self.catalog_search.connect('search-changed', self.filter_catalog)
        catalog_outer.pack_start(self.catalog_search, False, False, 0)
        catalog_scroll = Gtk.ScrolledWindow()
        catalog_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        catalog_scroll.set_max_content_height(420)
        catalog_scroll.set_propagate_natural_height(True)
        catalog_scroll.add(self.add_catalog)
        catalog_outer.pack_start(catalog_scroll, True, True, 0)
        catalog_outer.show_all()
        self.add_popover.add(catalog_outer)
        toolbar.pack_start(self.add_button, False, False, 0)
        self.summary = Gtk.Label(xalign=0)
        self.summary.get_style_context().add_class('dim-label')
        toolbar.pack_start(self.summary, True, True, 0)
        more = Gtk.MenuButton(label=_tr('更多'))
        popover = Gtk.Popover.new(more)
        popover.get_style_context().add_class('adws-settings-popover')
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for caption, callback in [('安装 .mplg…', self.on_add_plugin), ('刷新组件', lambda *_: self.refresh_components()),
                                  ('恢复默认布局', self.on_reset), ('打开插件目录', self.on_open_plugin_dir)]:
            button = Gtk.Button(label=_tr(caption))
            button.connect('clicked', lambda button, fn=callback: (popover.popdown(), fn(button)))
            actions.pack_start(button, False, False, 0)
        popover.add(actions)
        actions.show_all()
        popover.set_no_show_all(True)
        more.set_popover(popover)
        toolbar.pack_end(more, False, False, 0)
        outer.pack_start(toolbar, False, False, 0)

        preview_title = Gtk.Label(label=_tr('布局实时预览'), xalign=0)
        preview_title.get_style_context().add_class('title')
        outer.pack_start(preview_title, False, False, 0)
        from adws_layout_preview import create_preview
        self.preview = create_preview(self.select_preview_component, self.drag_move)
        outer.pack_start(self.preview, False, False, 0)
        self.content.connect('destroy', self.close_preview)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class('dim-label')
        self.status.set_line_wrap(True)
        outer.pack_start(self.status, False, False, 0)
        editor = Gtk.Box(spacing=16)
        outer.pack_start(editor, True, True, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_overlay_scrolling(False)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.sections = {}
        for slot, caption in [('left', '前部'), ('center', '中间'), ('right', '后部')]:
            section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            heading = Gtk.Label(label=_tr(caption), xalign=0)
            heading.get_style_context().add_class('settings-group')
            section.pack_start(heading, False, False, 0)
            rows = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            rows.set_halign(Gtk.Align.START)
            zone_scroll = Gtk.ScrolledWindow()
            zone_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            zone_scroll.set_overlay_scrolling(False)
            zone_scroll.set_min_content_height(92)
            zone_scroll.add(rows)
            section.pack_start(zone_scroll, False, False, 0)
            self.bind_drop(rows, slot)
            self.bind_drop(zone_scroll, slot)
            self.sections[slot] = rows
            self.list_box.pack_start(section, False, False, 0)
        scroller.add(self.list_box)
        editor.pack_start(scroller, True, True, 0)
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_overlay_scrolling(False)
        self.inspector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.inspector.set_size_request(240, -1)
        self.inspector.get_style_context().add_class('layout-inspector')
        detail_scroll.add(self.inspector)
        editor.pack_start(detail_scroll, False, False, 0)
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
        for widget in (self.start_mode, self.start_label, self.launcher_mode, self.launcher_command,
                       self.menu_theme, self.menu_css, self.start_right_mode, self.start_right_custom, *self.start_images.values()):
            widget.connect('changed', self.changed)
        if not self.embedded:
            self.window.show_all()
        if open_plugin:
            from gi.repository import GLib
            GLib.idle_add(self.open_plugin_settings, open_plugin)

        from gi.repository import GLib
        self.health_source = GLib.timeout_add(1000, self.refresh_plugin_health)

    def refresh_plugin_health(self):
        if self.closed:
            self.health_source = 0
            return False
        from adws_plugin_watchdog import health
        for entry in self.rows:
            if entry['kind'] != 'plugin': continue
            record = health(entry['instance'])
            failed = bool(record and record['state'] == 'failed')
            badge = entry.get('health_badge')
            if badge is None: continue
            badge.set_visible(failed)
            style = entry['box'].get_style_context()
            if failed:
                style.add_class('plugin-failed')
                entry['box'].set_tooltip_text(_tr('插件异常')+'：'+str(record.get('reason','')))
            else:
                style.remove_class('plugin-failed')
                entry['box'].set_tooltip_text(None)
        return True

    # ---------- 行构建 ----------

    def changed(self, *_):
        self.schedule_preview()
        if not self.loading and self.on_changed:
            self.on_changed()

    def _clear_rows(self):
        self.selected_entry = None
        for child in self.inspector.get_children():
            self.inspector.remove(child)
            child.destroy()
        for section in self.sections.values():
            for child in section.get_children():
                section.remove(child)
                child.destroy()
        for row in self.rows:
            for holder in row.get('control_boxes', {}).values(): holder.destroy()
        self.rows = []

    def _add_row(self, entry):
        Gtk = self.Gtk
        from gi.repository import Pango
        button = Gtk.Button()
        button.get_style_context().add_class('layout-component')
        button.connect('clicked', lambda *_: self.select_entry(entry))
        box = Gtk.Box(spacing=10)
        icon = {"start": "view-app-grid-symbolic", "windows": "view-grid-symbolic",
                "workspaces": "view-dual-symbolic", "clock": "preferences-system-time-symbolic",
                "tray": "view-more-symbolic", "sound": "audio-volume-high-symbolic", "brightness": "display-brightness-symbolic"}.get(entry['key'], 'application-x-addon-symbolic')
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        title = Gtk.Label(label=entry['name'], xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(14)
        title.get_style_context().add_class('title')
        labels.pack_start(title, False, False, 0)
        entry['name_label'] = title
        description = _tr('必须保留 · 唯一组件') if entry['key'] == 'windows' else (
            _tr('可重复添加') if entry['key'] in ('start', 'clock') or (entry['kind']=='plugin' and entry.get('manifest',{}).get('isSingleOnly') is not True) else _tr('单例组件'))
        subtitle = Gtk.Label(label=description, xalign=0)
        subtitle.get_style_context().add_class('dim-label')
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle.set_max_width_chars(18)
        labels.pack_start(subtitle, False, False, 0)
        box.pack_start(labels, True, True, 0)
        if entry['kind'] == 'plugin':
            language = entry.get('manifest', {}).get('language', 'python')
            caption, color = {'python': ('Python', '#326b99'), 'shell': ('Shell', '#326b40'),
                              'binary': (_tr('原生'), '#595969')}.get(language, (_tr('未知'), '#595969'))
            badge = Gtk.Label(label='+ ' + caption)
            badge.get_style_context().add_class('plugin-language')
            provider = Gtk.CssProvider()
            provider.load_from_data(('label.plugin-language { background: ' + color + '; color: white; border-radius: 6px; padding: 2px 7px; font-size: .85em; }').encode())
            badge.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            box.pack_end(badge, False, False, 0)
            entry['language_badge'] = badge
            warning = Gtk.Label(label=_tr('异常'))
            warning.get_style_context().add_class('plugin-health-warning')
            warning.set_no_show_all(True)
            labels.pack_start(warning, False, False, 0)
            entry['health_badge'] = warning
            provider = Gtk.CssProvider()
            provider.load_from_data(b"button.plugin-failed {border:1px solid #d7ad38;} label.plugin-health-warning {color:#e9bc46;}")
            button.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER+20)
            warning.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER+20)
        elif entry['key'] == 'windows':
            box.pack_end(Gtk.Image.new_from_icon_name('changes-prevent-symbolic', Gtk.IconSize.BUTTON), False, False, 0)
        button.add(box)
        switch = Gtk.Switch()
        switch.set_halign(Gtk.Align.START)
        switch.set_valign(Gtk.Align.CENTER)
        switch.set_active(entry.get('enabled', True))
        switch.set_sensitive(entry['key'] != 'windows')
        switch.connect('notify::active', self.changed)
        slot = Gtk.ComboBoxText()
        for key, name in adws_layout.SLOT_NAMES.items():
            slot.append(key, name)
        slot.set_active_id(entry['slot'])
        slot.connect('changed', lambda combo: self.change_slot(entry, combo.get_active_id()))
        width = Gtk.SpinButton.new_with_range(0, 512, 4)
        width.set_value(entry.get('width', 0))
        width.connect('value-changed', self.changed)
        entry['widgets'] = {'switch': switch, 'slot': slot, 'width': width}
        entry['control_boxes'] = {}
        for key, widget in entry['widgets'].items():
            holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            holder.pack_start(widget, False, False, 0)
            entry['control_boxes'][key] = holder
        entry['box'] = button
        button.drag_source_set(1 << 8, [Gtk.TargetEntry.new('application/x-adws-layout-instance', Gtk.TargetFlags.SAME_APP, 0)], self.Gdk.DragAction.MOVE)
        button.connect('drag-data-get', lambda _, context, selection, info, time: selection.set(selection.get_target(), 8, entry['instance'].encode()))
        self.bind_drop(button, entry['slot'], entry)
        self.rows.append(entry)
        self.sections[entry['slot']].pack_start(button, False, False, 0)

    def bind_drop(self, widget, slot, entry=None):
        Gtk, Gdk = self.Gtk, self.Gdk
        widget.drag_dest_set(Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new('application/x-adws-layout-instance', Gtk.TargetFlags.SAME_APP, 0)], Gdk.DragAction.MOVE)
        def received(widget, context, x, y, selection, info, time):
            try: identity = bytes(selection.get_data()).decode('utf-8')
            except (TypeError, UnicodeError): identity = ''
            actual_slot = entry['slot'] if entry else slot
            success = self.drag_move(identity, actual_slot, entry['instance'] if entry else None,
                                     bool(entry and x > widget.get_allocated_width()/2))
            Gtk.drag_finish(context, success, False, time)
        widget.connect('drag-data-received', received)

    def drag_move(self, identity, slot, anchor=None, after=False):
        row = next((r for r in self.rows if r['instance'] == identity), None)
        if row is None or not adws_layout.move_component(self.rows, identity, slot, anchor, after):
            return False
        row['widgets']['slot'].set_active_id(slot)
        self.paint_sections()
        self.select_entry(row)
        self.changed()
        return True


    def paint_sections(self):
        boxes = [row['box'] for row in self.rows]
        for section in self.sections.values():
            for child in section.get_children():
                section.remove(child)
                if child not in boxes: child.destroy()
        for slot, section in self.sections.items():
            entries = [row for row in self.rows if row['slot'] == slot]
            for row in entries:
                section.pack_start(row['box'], False, False, 0)
            if not entries:
                hint = self.Gtk.Label(label=_tr('此区域为空，可添加或移入组件。'), xalign=0)
                hint.get_style_context().add_class('dim-label')
                section.pack_start(hint, False, False, 0)
        self.list_box.show_all()
        self.refresh_plugin_health()
        self.schedule_preview()
        self.summary.set_text(_tr('%s 个组件') % len(self.rows))
        self.refresh_catalog()
        self.refresh_start_choices()

    def schedule_preview(self, *_):
        if not self.closed and not self.preview_source and hasattr(self, 'preview'):
            from gi.repository import GLib
            self.preview_source = GLib.idle_add(self.refresh_preview)

    def refresh_preview(self):
        self.preview_source = 0
        if not hasattr(self, 'layout'): return False
        options = dict(self.layout.get('options', {}))
        # Read the actual panel appearance; pending controls override it below.
        config = getattr(self.window, 'config', None)
        if config and hasattr(config, 'read_taskbar_overrides'):
            _, color, radius, family, size = config.read_taskbar_overrides()
            options.update({'_surface_background': self.Gdk.RGBA(*color).to_string(),
                            'preview_radius': radius, 'font_family': family, 'font_size': size})
        if self.get_preview_options:
            options.update(self.get_preview_options())
        if 'start_label' not in options:
            import html
            definition = adws_layout.launcher_definition()
            options['start_label'] = html.unescape(str(definition.get('format') or _tr('开始')))
        rows = []
        for row in self.rows:
            overrides = copy.deepcopy(row.get('options', {}))
            if row['key'] == 'start' and row.get('instance') == self.start_instance:
                overrides.update(self.read_start_controls(validate=False))
            rows.append({'key': row['key'], 'name': row['name'], 'instance': row.get('instance', row['key']),
                         'slot': row['widgets']['slot'].get_active_id() or 'left',
                         'enabled': row['widgets']['switch'].get_active(),
                         'width': int(row['widgets']['width'].get_value()), 'options': overrides,
                         'settings':copy.deepcopy(row.get('settings',{}))})
        self.preview.update(rows, options)
        return False

    def select_preview_component(self, identity):
        row = next((row for row in self.rows if row.get('instance', row['key']) == identity), None)
        if row: self.select_entry(row)

    def close_preview(self, *_):
        self.closed = True
        if getattr(self, 'health_source', 0):
            from gi.repository import GLib
            GLib.source_remove(self.health_source)
            self.health_source = 0
        for row in self.rows:
            for holder in row.get('control_boxes', {}).values(): holder.destroy()
        if self.preview_source:
            from gi.repository import GLib
            GLib.source_remove(self.preview_source)
            self.preview_source = 0

    def select_entry(self, entry):
        Gtk = self.Gtk
        self.selected_entry = entry
        for row in self.rows:
            context = row['box'].get_style_context()
            context.remove_class('selected-component')
        entry['box'].get_style_context().add_class('selected-component')
        holders = [holder for row in self.rows for holder in row.get('control_boxes', {}).values()]
        for child in self.inspector.get_children():
            self.inspector.remove(child)
            if child not in holders: child.destroy()
        title = Gtk.Label(label=entry['name'], xalign=0)
        title.get_style_context().add_class('title')
        title.set_line_wrap(True)
        self.inspector.pack_start(title, False, False, 0)
        if entry['key'] == 'windows':
            label = Gtk.Label(label=_tr('窗口图标栏始终保留，不能停用或移除。'), xalign=0)
            label.set_line_wrap(True)
            self.inspector.pack_start(label, False, False, 0)
        else:
            self.inspector.pack_start(Gtk.Label(label=_tr('显示组件'), xalign=0), False, False, 0)
            switch = entry['control_boxes']['switch']
            if switch.get_parent(): switch.get_parent().remove(switch)
            self.inspector.pack_start(switch, False, False, 0)
        for name, widget in [(_tr('位置'), entry['control_boxes']['slot'])] + (
            [(_tr('占位宽度（0 为自适应）'), entry['control_boxes']['width'])] if entry['editable_width'] else []):
            self.inspector.pack_start(Gtk.Label(label=name, xalign=0), False, False, 0)
            if widget.get_parent(): widget.get_parent().remove(widget)
            self.inspector.pack_start(widget, False, False, 0)
        move = Gtk.Box(spacing=6)
        for caption, delta in [('向前移', -1), ('向后移', 1)]:
            button = Gtk.Button(label=_tr(caption))
            button.connect('clicked', lambda _, direction=delta: self.move_row(entry, direction))
            move.pack_start(button, True, True, 0)
        self.inspector.pack_start(move, False, False, 0)
        if entry['key'] in ('start', 'clock') or (entry['kind'] == 'plugin' and (entry['manifest'].get('settingsSchema') or 'panel.rows-v1' in entry['manifest'].get('interfaces', []))):
            settings = Gtk.Button(label=_tr('组件设置…'))
            settings.connect('clicked', lambda *_: self.configure_entry(entry))
            self.inspector.pack_start(settings, False, False, 0)
        if entry['key'] != 'windows':
            remove = Gtk.Button(label=_tr('移除组件'))
            remove.connect('clicked', lambda *_: self.remove_entry(entry))
            self.inspector.pack_start(remove, False, False, 0)
        self.inspector.show_all()
        if self.embedded and hasattr(self, 'protect_scroll'):
            self.protect_scroll(self.inspector)
        from adws_settings_widgets import enhance_choices
        enhance_choices(self.inspector, translate=_tr)

    def configure_entry(self, entry):
        if entry['key'] == 'start':
            self.start_instance_choice.set_active_id(entry['instance'])
            if self.on_start_settings: self.on_start_settings()
            else: self.start_mode.grab_focus()
        elif entry['key'] == 'clock':
            self.on_clock_settings(entry=entry)
        else:
            self.on_plugin_settings(entry)

    def refresh_catalog(self):
        Gtk = self.Gtk
        for child in self.add_catalog.get_children():
            self.add_catalog.remove(child)
            child.destroy()
        self.catalog_buttons = []
        for item in adws_layout.component_catalog(self.available):
            present = any(row['kind'] == item['kind'] and row['key'] == item['key'] for row in self.rows)
            button = Gtk.Button()
            content = Gtk.Box(spacing=10)
            content.pack_start(Gtk.Image.new_from_icon_name(item['icon'], Gtk.IconSize.BUTTON), False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            texts.pack_start(Gtk.Label(label=item['name'], xalign=0), False, False, 0)
            hint = _tr('已添加') if present and not item['repeatable'] else (_tr('可重复添加') if item['repeatable'] else _tr('单例组件'))
            sub = Gtk.Label(label=hint, xalign=0)
            sub.get_style_context().add_class('dim-label')
            texts.pack_start(sub, False, False, 0)
            content.pack_start(texts, True, True, 0)
            button.add(content)
            button.set_sensitive(item['repeatable'] or not present)
            button.connect('clicked', lambda _, component=item: self.add_component(component['kind'], component['key']))
            self.add_catalog.pack_start(button, False, False, 0)
            self.catalog_buttons.append((button, item['name']))
        self.add_catalog.show_all()
        self.filter_catalog()

    def filter_catalog(self, *_):
        query = self.catalog_search.get_text().strip().casefold()
        for button, name in getattr(self, 'catalog_buttons', []):
            button.set_visible(not query or query in name.casefold())

    def add_component(self, kind, key):
        state = self.collect_layout()
        if kind == 'builtin':
            inactive = next((item for item in state['builtins'] if item['id'] == key and not item['enabled']), None)
            if inactive:
                value = inactive
                value['enabled'] = True
            else:
                value = adws_layout.new_builtin(key, state['builtins'], state['options'])
                state['builtins'].append(value)
        else:
            manifest=next(item['manifest'] for item in self.available if item.get('ok') and item['manifest']['id']==key)
            value=adws_layout.new_plugin(manifest,state['plugins'])
        self.add_popover.popdown()
        self.reload(state)
        row = next(row for row in self.rows if row['kind'] == kind and row.get('instance') == value.get('instance'))
        self.select_entry(row)
        self.changed()

    def remove_entry(self, entry):
        if entry['key'] == 'windows':
            return False
        state = self.collect_layout()
        if entry['kind'] == 'builtin':
            state['builtins'] = [item for item in state['builtins'] if item['instance'] != entry['instance']]
        else:
            for item in state['plugins']:
                if item.get('instance',item['package']) == entry['instance']: item['enabled'] = False
        self.reload(state)
        self.changed()
        return True

    def refresh_components(self):
        self.reload(self.collect_layout())

    def apply_keyboard_profile(self, _button=None):
        from adws_keyboard import apply_profile
        try:
            apply_profile(self.keyboard_profile.get_active_id())
        except (OSError, ValueError) as exc:
            self.show_message(_tr('应用失败'), str(exc), error=True)
            return
        self.status.set_text(_tr('键位方案已应用，Niri 将自动重载。'))

    def reload(self, layout=None):
        self.loading = True
        self._clear_rows()
        if layout is None:
            layout = load_layout(self.layout_file)
        layout = adws_layout.normalize_layout(layout)
        self.layout = copy.deepcopy(layout)
        self.start_instance = 'start'
        options = layout.get("options", {})
        self.clock_options = None
        try:
            definition = adws_layout.launcher_definition()
        except (OSError, ValueError):
            definition = {}
        current = definition.get("format", _tr('开始'))
        command = options.get("start_launcher_command", definition.get("on-click", "fuzzel"))
        command = command if isinstance(command, str) and command.strip() else "fuzzel"
        self.rofi_themed = command.strip() == rofi_theme_command()
        mode = {"fuzzel": "fuzzel", "rofi -show drun": "rofi",
                rofi_theme_command(): "rofi", native_menu_command(): "adws"}.get(command.strip(), "custom")
        if options.get("start_launcher_mode") == "adws": mode = "adws"
        self.menu_theme.set_active_id(options.get("start_menu_theme", "kde"))
        if self.menu_theme.get_active_id() is None: self.menu_theme.set_active_id("kde")
        self.menu_css.set_text(options.get("start_menu_css", ""))
        self.launcher_command.set_text(options.get("start_launcher_custom", command if mode == "custom" else ""))
        self.launcher_mode.set_active_id(mode)
        self.load_start_right_controls(options)
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

        self.available = list(available.values())
        builtin_rows = []
        for stored in layout['builtins']:
            if not stored['enabled'] and stored['id'] != 'windows':
                continue
            builtin_id = stored['id']
            info = BUILTIN_INFO[builtin_id]
            builtin_rows.append({**stored, 'kind': 'builtin', 'key': builtin_id,
                                 'name': info['name'], 'width': 0, 'editable_width': False})
        plugin_rows = []
        for stored in layout.get('plugins',[]):
            package_id=stored['package']
            entry=available.get(package_id)
            if entry is None or not stored.get('enabled',False):continue
            manifest=entry['manifest']
            defaults = normalize_plugin_defaults(manifest)
            width = stored.get("width", defaults["width"])
            if width is None:
                width = defaults["width"]
            plugin_rows.append({
                "kind": "plugin",
                "key": package_id,
                "instance":stored["instance"],
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
        totals = {key: sum(row['key'] == key for row in rows) for key in {row['key'] for row in rows}}
        counts = {key:0 for key in totals}
        for entry in rows:
            key = entry['key']
            if key in counts and totals[key] > 1:
                counts[key] += 1
                entry['name'] = _tr('%s %s') % (entry['name'], counts[key])
            self._add_row(entry)
        self.paint_sections()
        self.loading = False
        if self.rows: self.select_entry(self.rows[0])
        self.update_status(layout)

    def update_status(self, _layout=None):
        self.status.set_text(_tr('移除只影响布局，插件文件与设置会保留。'))

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
        self.paint_sections()
        self.changed()

    def move_row(self, entry, delta):
        index = self.rows.index(entry)
        other = index + delta
        if other < 0 or other >= len(self.rows):
            return
        if self.rows[other].get("slot") != entry.get("slot"):
            return
        self.rows[index], self.rows[other] = self.rows[other], self.rows[index]
        self.paint_sections()
        self.changed()

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
            self.refresh_components()
        else:
            dialog.destroy()

    def on_remove_plugin(self, entry):
        return self.remove_entry(entry)

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
            defaults = {'apiVersion': 2, 'options': copy.deepcopy(self.collect_layout()['options']),
                        'builtins': adws_layout.default_layout()['builtins'],
                        'plugins': [{**item, 'enabled': False} for item in self.layout.get('plugins', [])]}
            if self.embedded:
                self.reload(defaults)
                self.status.set_text(_tr('布局已恢复默认，点击应用后生效。'))
                if self.on_changed:
                    self.on_changed()
                return
            save_layout(defaults, self.layout_file)
        except (OSError, ValueError) as exc:
            self.show_message(_tr('恢复失败'), str(exc))
            return
        self.reload()

    def on_plugin_settings(self, entry):
        from adws_plugin_settings import SettingsDialog, validate_settings
        from adws_plugin_api import canonical_id
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
            self.changed()
            if not self.embedded: self.save_layout(restart=True)

    def open_plugin_settings(self, package_id):
        from adws_plugin_api import canonical_id
        package_id,_,instance=package_id.partition('#')
        package_id = canonical_id(package_id)
        entry = next((row for row in self.rows
                      if row.get("kind") == "plugin" and row.get("key") == package_id and (not instance or row.get("instance")==instance)), None)
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
        # Native menu preferences remain accessible with another launcher or a hidden Start button.

    def preview_start_menu(self, *_):
        import subprocess
        command = ['bash', str(adws_layout.PROJECT_ROOT / 'adws'), 'start-menu', '--theme', self.menu_theme.get_active_id() or 'kde']
        path = self.menu_css.get_text().strip()
        command += ['--css', str(Path(path).expanduser()) if path else '']
        try:
            subprocess.Popen(command, start_new_session=True)
        except OSError as error:
            self.show_message(_tr('无法打开开始菜单'), str(error), error=True)

    def on_rofi_theme(self, *_):
        self.rofi_themed = True
        self.changed()
        self.status.set_text(_tr('已设置 ADWS rofi 主题，点击“应用并重启任务栏”生效。'))

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
            name, glyph = adws_layout.distro_logo()
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
            adws_layout.validate_start_images(self.image_options())
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

    def on_clock_settings(self, _button=None, entry=None):
        from adws_clock import ClockDialog
        entry = entry or next((row for row in self.rows if row['key'] == 'clock'), None)
        if entry is None: return
        options = adws_layout.instance_options(self.layout, entry)
        dialog = ClockDialog(options, self.window)
        try:
            values = dialog.run()
            if values is not None:
                entry.setdefault('options', {})['clock'] = values
                self.changed()
                self.status.set_text(_tr('时钟设置已修改，点击应用后生效。'))
        finally:
            dialog.dialog.destroy()

    def update_start_right_controls(self, *_):
        custom = self.start_right_mode.get_active_id() == 'custom'
        self.start_right_custom.set_sensitive(custom)
        self.start_right_custom.set_visible(custom)

    def load_start_right_controls(self, options):
        self.start_right_custom.set_text(str(options.get('start_right_custom') or ''))
        self.start_right_mode.set_active_id(options.get('start_right_mode', 'settings'))
        if self.start_right_mode.get_active_id() is None:
            self.start_right_mode.set_active_id('settings')
        self.update_start_right_controls()

    def read_start_controls(self, validate=True):
        images = self.image_options()
        if validate and self.start_enabled.get_active():
            adws_layout.validate_start_images(images)
        custom = self.launcher_command.get_text().strip()
        mode = self.launcher_mode.get_active_id()
        command = {'adws': native_menu_command(), 'fuzzel': 'fuzzel',
                   'rofi': rofi_theme_command() if self.rofi_themed else 'rofi -show drun'}.get(mode, custom)
        if validate and (not command or '\x00' in command):
            raise ValueError(_tr('请输入启动器命令。'))
        right_mode = self.start_right_mode.get_active_id() or 'settings'
        right_custom = self.start_right_custom.get_text().strip()
        if validate and right_mode == 'custom' and (not right_custom or '\x00' in right_custom):
            raise ValueError(_tr('请输入右键自定义命令。'))
        return {'start_right_mode': right_mode, 'start_right_custom': right_custom,
                **images, 'start_label': self.start_label.get_text().strip(),
                'start_launcher_command': command, 'start_launcher_custom': custom,
                'start_launcher_mode': mode}

    def flush_start_controls(self, validate=True):
        if not hasattr(self, 'layout'): return
        values = self.read_start_controls(validate)
        row = next((row for row in self.rows if row.get('instance') == self.start_instance and row['key'] == 'start'), None)
        if self.start_instance == 'start':
            self.layout['options'].update(values)
            if row: row['options'] = {}  # canonical instance retains global defaults
        elif row:
            row.setdefault('options', {}).update(values)

    def refresh_start_choices(self):
        choice = self.start_instance_choice
        was_loading = self.loading
        self.loading = True
        choice.remove_all()
        starts = [row for row in self.rows if row['key'] == 'start']
        if not any(row.get('instance') == 'start' for row in starts):
            choice.append('start', _tr('默认设置（未添加）'))
        for index,row in enumerate(starts, 1):
            choice.append(row['instance'], _tr('开始按钮 %s') % index)
        choice.set_active_id(self.start_instance)
        if choice.get_active_id() is None:
            self.start_instance = 'start'
            choice.set_active_id('start')
        self.start_enabled.set_active(any(row['key'] == 'start' and row.get('instance') == self.start_instance for row in self.rows))
        self.loading = was_loading

    def change_start_instance(self, combo):
        target = combo.get_active_id()
        if self.loading or not target or target == self.start_instance: return
        self.flush_start_controls(validate=False)
        self.start_instance = target
        row = next((row for row in self.rows if row.get('instance') == target and row['key'] == 'start'), {})
        options = adws_layout.instance_options(self.layout, row)
        self.loading = True
        self.start_label.set_text(options.get('start_label', _tr('开始')))
        self.start_mode.set_active_id(options.get('start_icon_mode', 'custom'))
        for key, entry in self.start_images.items(): entry.set_text(options.get(key, ''))
        command = options.get('start_launcher_command', 'fuzzel')
        self.rofi_themed = command == rofi_theme_command()
        mode = options.get('start_launcher_mode') or {'fuzzel': 'fuzzel', 'rofi -show drun': 'rofi', rofi_theme_command(): 'rofi', native_menu_command(): 'adws'}.get(command, 'custom')
        self.launcher_command.set_text(options.get('start_launcher_custom', command if mode == 'custom' else ''))
        self.launcher_mode.set_active_id(mode)
        self.load_start_right_controls(options)
        self.start_enabled.set_active(bool(row))
        self.loading = False
        self.schedule_preview()

    def toggle_start_instance(self, check):
        if self.loading: return
        row = next((row for row in self.rows if row['key'] == 'start' and row.get('instance') == self.start_instance), None)
        if check.get_active() and row is None:
            self.add_component('builtin', 'start')
        elif not check.get_active() and row is not None:
            self.remove_entry(row)

    def collect_layout(self) -> dict:
        self.flush_start_controls()
        layout = copy.deepcopy(self.layout)
        builtins, plugins = [], []
        counters = {'left': 0, 'center': 0, 'right': 0}
        for row in self.rows:
            widgets = row['widgets']
            slot = widgets['slot'].get_active_id() or 'left'
            order = counters[slot]
            counters[slot] += 1
            if row['kind'] == 'builtin':
                builtins.append({'id': row['key'], 'instance': row['instance'],
                                 'enabled': True if row['key'] == 'windows' else bool(widgets['switch'].get_active()),
                                 'slot': slot, 'order': order, 'options': copy.deepcopy(row.get('options', {}))})
            else:
                plugins.append({'package': row['key'], 'instance': row['instance'], 'enabled': bool(widgets['switch'].get_active()),
                                'slot': slot, 'order': order, 'width': int(widgets['width'].get_value()),
                                'animations': row.get('animations') is True, 'settings': dict(row.get('settings') or {})})
        visible_plugins = {item['instance'] for item in plugins}
        # Retain unavailable/removed plugin settings without rediscovering a removed row.
        plugins.extend(item for item in layout.get('plugins', []) if item.get('instance',item.get('package')) not in visible_plugins)
        visible_instances = {item['instance'] for item in builtins}
        builtins.extend(item for item in layout.get('builtins', [])
                        if item['instance'] not in visible_instances and not item['enabled'])
        layout['builtins'], layout['plugins'] = builtins, plugins
        layout['options']['start_menu_theme'] = self.menu_theme.get_active_id() or 'kde'
        css_path = self.menu_css.get_text().strip()
        if self.launcher_mode.get_active_id() == 'adws' and css_path and not Path(css_path).expanduser().is_file():
            raise ValueError(_tr('自定义 CSS 文件不存在。'))
        layout['options']['start_menu_css'] = str(Path(css_path).expanduser().resolve()) if css_path else ''
        layout['apiVersion'] = 2
        return adws_layout.normalize_layout(layout)

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


def run(layout_file=None, open_plugin=None, start_instance=None) -> int:
    from gi.repository import GLib
    # Wayland's app_id comes from prgname, not the X11 program class.
    GLib.set_prgname("adws-layout")
    Gdk, Gtk = _gtk()
    Gdk.set_program_class("adws-layout")
    import importlib.util
    spec = importlib.util.spec_from_file_location("adws_config", Path(__file__).with_name("adws-config.py"))
    settings = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = settings
    spec.loader.exec_module(settings)
    if start_instance and layout_file is None and open_plugin is None:
        return settings.main(['--tab', 'start', '--start-instance', start_instance])
    owner = settings.TaskbarSettingsWindow(tab="start" if start_instance else "layout", layout_file=layout_file, open_plugin=open_plugin)
    if start_instance:
        owner.layout_editor.start_instance_choice.set_active_id(start_instance)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

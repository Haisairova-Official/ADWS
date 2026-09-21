#!/usr/bin/env python3
"""First-run setup, with deferred writes and a single wizard per user."""
import argparse
import copy
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import threading

from adws_i18n import tr as _tr


def folder():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'adws'


def needed():
    return not any((folder() / name).is_file() for name in ('taskbar-layout.json', 'setup.json'))


def launch(automatic=False):
    if automatic and not needed():
        return
    if not (os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY')):
        return
    env = dict(os.environ)
    env.pop('GDK_BACKEND', None)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *(['--auto'] if automatic else [])],
                     env=env, start_new_session=True)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def background_style(text, color):
    marker = '/* ==== ADWS 任务栏样式（自动生成）==== */'
    before, found, section = text.partition(marker)
    rule = r'(window#waybar\s*>\s*box\s*\{[^}]*?background\s*:\s*)[^;}]+'
    if found and re.search(rule, section):
        return before + found + re.sub(rule, lambda m: m[1]+color, section, count=1)
    return text + '\n' + ('' if found else marker+'\n') + 'window#waybar > box { background: '+color+'; }\n'


def run():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, Gio, GLib
    GLib.set_prgname('adws-setup')
    Gdk.set_program_class('adws-setup')
    from adws_layout import load_layout, apply_layout, live_config_path, live_style_path
    from adws_theme import start
    Gtk.init([])
    start()
    layout = copy.deepcopy(load_layout())
    options = layout.setdefault('options', {})
    window = Gtk.Window(title=_tr('ADWS 初始设置'))
    window.set_wmclass('adws-setup', 'adws-setup')
    window.set_default_size(640, 480)
    window.set_resizable(False)
    window.set_position(Gtk.WindowPosition.CENTER)
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin=24)
    window.add(outer)
    progress = Gtk.Label(xalign=0)
    outer.pack_start(progress, False, False, 0)
    stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=200)
    outer.pack_start(stack, True, True, 0)
    pages = []

    def page(title, description):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        heading = Gtk.Label(xalign=0)
        heading.set_markup('<big><b>' + GLib.markup_escape_text(_tr(title)) + '</b></big>')
        box.pack_start(heading, False, False, 0)
        label = Gtk.Label(label=_tr(description), xalign=0, wrap=True)
        label.set_max_width_chars(60)
        box.pack_start(label, False, False, 0)
        stack.add_named(box, str(len(pages)))
        pages.append(box)
        return box

    page('欢迎使用 ADWS', '用几步设置你的桌面。所有选择在点击“完成设置”后保存，之后也能随时修改。')
    effects = page('动效与任务栏', '选择你喜欢的流畅程度。关闭动效仍可正常使用全部功能。')
    toggles = {}
    for key, caption in [('window_animations', '窗口悬停与聚焦颜色渐变'), ('tab_animations', '设置选项卡淡入淡出'), ('group_windows', '堆叠同一应用的窗口'), ('window_peek', '悬停显示窗口画面预览')]:
        control = Gtk.CheckButton(label=_tr(caption))
        control.set_active(options.get(key, key == 'group_windows'))
        effects.pack_start(control, False, False, 0)
        toggles[key] = control
    speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 80, 600, 20)
    speed.set_value(options.get('animation_duration', 280))
    effects.pack_start(Gtk.Label(label=_tr('动效时长（毫秒）：'), xalign=0), False, False, 0)
    effects.pack_start(speed, False, False, 0)
    toggles['tab_animations'].connect('toggled', lambda c: stack.set_transition_duration(200 if c.get_active() else 0))
    stack.set_transition_duration(200 if toggles['tab_animations'].get_active() else 0)
    colors = page('颜色配置', '跟随系统配色，或为悬停和聚焦选择独立颜色。')
    follow = Gtk.CheckButton(label=_tr('跟随系统配色'))
    follow.set_active(not any(options.get(k) for k in ('hover_color', 'focus_color', 'focus_text_color')))
    colors.pack_start(follow, False, False, 0)
    picks = {}
    preview = Gtk.Button(label=_tr('配色预览：将鼠标移到这里'))
    preview.set_name('adws-setup-preview')
    provider = Gtk.CssProvider()
    preview.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    def preview_colors(*_):
        custom = not follow.get_active()
        for picker in picks.values(): picker.set_sensitive(custom)
        css = '' if not custom else '#adws-setup-preview {background:'+picks['focus_color'].get_rgba().to_string()+';color:'+picks['focus_text_color'].get_rgba().to_string()+';} #adws-setup-preview:hover {background:'+picks['hover_color'].get_rgba().to_string()+';}'
        provider.load_from_data(css.encode())
    for key, caption, default in [('background_color', '任务栏背景：', '#20252e'), ('hover_color', '窗口悬停颜色：', '#506680'), ('focus_color', '聚焦窗口颜色：', '#385b9c'), ('focus_text_color', '聚焦窗口文字：', '#ffffff')]:
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label=_tr(caption), xalign=0), True, True, 0)
        rgba = Gdk.RGBA(); rgba.parse(options.get(key) or default)
        picker = Gtk.ColorButton(rgba=rgba)
        picks[key] = picker
        picker.connect('color-set', preview_colors)
        row.pack_end(picker, False, False, 0)
        colors.pack_start(row, False, False, 0)
    colors.pack_start(preview, False, False, 0)
    follow.connect('toggled', preview_colors)
    preview_colors()
    apps = page('默认应用', '只列出已安装的应用；选择“保持当前设置”不会更改系统默认应用。')
    choices = {}
    for caption, mime in [('网页浏览器', 'x-scheme-handler/https'), ('文件管理器', 'inode/directory'), ('文本编辑器', 'text/plain')]:
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label=_tr(caption), xalign=0), False, False, 0)
        combo = Gtk.ComboBoxText()
        combo.append('', _tr('保持当前设置'))
        seen = set()
        for app in sorted(Gio.AppInfo.get_all_for_type(mime), key=lambda a: a.get_display_name().casefold()):
            if app.get_id() and app.get_id() not in seen and app.should_show():
                combo.append(app.get_id(), app.get_display_name()); seen.add(app.get_id())
        combo.set_active(0)
        row.pack_end(combo, True, True, 0)
        apps.pack_start(row, False, False, 0)
        choices[mime] = combo
    launcher = Gtk.ComboBoxText()
    launcher.append('', _tr('保持当前设置'))
    import shutil
    for executable, command in [('fuzzel', 'fuzzel'), ('rofi', 'rofi -show drun')]:
        if shutil.which(executable): launcher.append(command, executable)
    launcher.set_active(0)
    apps.pack_start(Gtk.Label(label=_tr('开始按钮启动器：'), xalign=0), False, False, 0)
    apps.pack_start(launcher, False, False, 0)
    from adws_wallpaper_page import WallpaperPage
    wallpaper = WallpaperPage(window, page('壁纸', '保留当前壁纸，或选择一张图片。壁纸工具可在高级选项中选择。'))
    final = page('准备就绪', '确认后保存设置，并刷新正在运行的任务栏。没有启动的组件会保持关闭。')
    summary = Gtk.Label(xalign=0, wrap=True)
    final.pack_start(summary, False, False, 0)
    error = Gtk.Label(xalign=0, wrap=True)
    outer.pack_start(error, False, False, 0)
    buttons = Gtk.Box(spacing=12)
    cancel = Gtk.Button(label=_tr('稍后设置'))
    back = Gtk.Button(label=_tr('上一步'))
    next_button = Gtk.Button(label=_tr('下一步'))
    buttons.pack_start(cancel, False, False, 0)
    buttons.pack_end(next_button, False, False, 0)
    buttons.pack_end(back, False, False, 0)
    outer.pack_start(buttons, False, False, 0)
    index = [0]
    busy = [False]

    def navigate(delta):
        index[0] += delta
        stack.set_visible_child_name(str(index[0]))
        progress.set_text(_tr('步骤 %s / %s') % (index[0]+1, len(pages)))
        back.set_sensitive(index[0] > 0)
        next_button.set_label(_tr('完成设置') if index[0] == len(pages)-1 else _tr('下一步'))
        summary.set_text('\n'.join([_tr('已开启：') + '、'.join(c.get_label() for c in toggles.values() if c.get_active()), _tr('跟随系统配色') if follow.get_active() else _tr('自定义颜色'), *[combo.get_active_text() for combo in choices.values() if combo.get_active_id()]]))
        summary.set_text(summary.get_text() + '\n' + (_tr('保持当前壁纸设置') if wallpaper.keep.get_active() else (_tr('壁纸') + ': ' + (wallpaper.selected or ''))))

    def apply():
        try:
            wallpaper_choice = wallpaper.selection()
        except Exception as exc:
            error.set_text(str(exc))
            return
        selected = {mime: combo.get_active_id() for mime, combo in choices.items() if combo.get_active_id()}
        options.update({key: c.get_active() for key, c in toggles.items()})
        options['animation_duration'] = int(speed.get_value())
        options.update({key: '' if follow.get_active() else picker.get_rgba().to_string() for key, picker in picks.items()})
        background = '@surface_container_high' if follow.get_active() else options['background_color']
        if launcher.get_active_id(): options['start_launcher_command'] = launcher.get_active_id()
        busy[0] = True
        buttons.set_sensitive(False)
        error.set_text(_tr('正在保存设置…'))
        def done(message):
            busy[0] = False
            buttons.set_sensitive(True)
            if message: error.set_text(message)
            else: window.destroy()
            return False
        def worker():
            from adws_runtime import pids
            config = folder().parent
            paths = [folder()/'taskbar-layout.json', folder()/'setup.json', folder()/'wallpaper.json', live_config_path(), live_style_path(), config/'mimeapps.list']
            backups = {}
            try:
                backups = {p: p.read_bytes() if p.is_file() else None for p in paths}
                for mime, desktop_id in selected.items():
                    app = Gio.DesktopAppInfo.new(desktop_id)
                    if app is None: raise ValueError(_tr('选择的应用已被移除，请重新选择。'))
                    for target in ([mime, 'x-scheme-handler/http', 'text/html'] if mime.endswith('/https') else [mime]):
                        if not app.set_as_default_for_type(target): raise RuntimeError(_tr('无法保存默认应用。'))
                if live_config_path().exists():
                    ok, message = apply_layout(layout, restart=False)
                    if not ok: raise RuntimeError(message)
                    style = live_style_path()
                    style.write_text(background_style(style.read_text(), background))
                write_json(folder()/'taskbar-layout.json', layout)
                write_json(folder()/'setup.json', {'version': 1, 'completed': True})
                if wallpaper_choice:
                    from adws_wallpaper import apply as apply_wallpaper
                    write_json(folder()/'wallpaper.json', {k: wallpaper_choice[k] for k in ('engine', 'image')})
                    apply_wallpaper(**wallpaper_choice)
            except Exception as exc:
                for p, content in backups.items():
                    if content is None: p.unlink(missing_ok=True)
                    else: p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(content)
                GLib.idle_add(done, str(exc)); return
            message = ''
            if pids('taskbar'):
                from adws_layout import restart_taskbar
                ok, detail = restart_taskbar()
                if not ok: message = detail
            GLib.idle_add(done, message)
        threading.Thread(target=worker, daemon=False).start()

    next_button.connect('clicked', lambda *_: apply() if index[0] == len(pages)-1 else navigate(1))
    back.connect('clicked', lambda *_: navigate(-1))
    cancel.connect('clicked', lambda *_: window.destroy() if not wallpaper.installing and not busy[0] else None)
    window.connect('delete-event', lambda *_: busy[0] or wallpaper.installing)
    window.connect('destroy', lambda *_: Gtk.main_quit())
    navigate(0)
    window.show_all()
    Gtk.main()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--auto', action='store_true')
    args = parser.parse_args()
    if args.auto and not needed(): return
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or folder())
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime/'adws-setup.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        run()


if __name__ == '__main__': main()

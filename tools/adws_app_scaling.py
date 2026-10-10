"""Per-application scaling through reversible user desktop entries."""
import math
import os
from pathlib import Path
import re
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gio, GLib, Gtk
from adws_i18n import tr
from adws_atomic import replace_files


def local_directory():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'applications'


def identity(app):
    name = app.get_id()
    if not name or Path(name).name != name or not name.endswith('.desktop'):
        raise ValueError(tr('应用没有有效的桌面启动项。'))
    return name


def key_file(path):
    data = GLib.KeyFile()
    data.load_from_file(str(path), GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    return data


def has_key(data, group, key):
    return key in data.get_keys(group)[0]


def scaling_command(command, factor, engine):
    factor = float(factor)
    if not math.isfinite(factor) or not .5 <= factor <= 4:
        raise ValueError(tr('缩放范围为 50%–400%。'))
    if engine not in ('qt', 'electron'):
        raise ValueError('Invalid scaling engine')
    # Strip only scaling arguments. Preserve desktop field codes and quoting.
    command = re.sub(r'(?<!\S)--force-device-scale-factor=\S+\s*', '', command)
    command = re.sub(r'(?<!\S)(?:QT_SCALE_FACTOR|QT_AUTO_SCREEN_SCALE_FACTOR|QT_FONT_DPI)=\S+\s*', '', command)
    if engine == 'qt':
        return f'/usr/bin/env QT_SCALE_FACTOR={factor:g} QT_AUTO_SCREEN_SCALE_FACTOR=0 QT_FONT_DPI=96 ' + command
    # Insert before file/URI arguments, never after %F which may expand to many.
    match = re.search(r'(?<!\S)%[fFuU]', command)
    offset = match.start() if match else len(command)
    return command[:offset].rstrip() + f' --force-device-scale-factor={factor:g} ' + command[offset:]


def save(app, factor, engine):
    name = identity(app)
    destination = local_directory()/name
    if destination.is_symlink():
        raise ValueError(tr('启动项是符号链接，请先检查该文件。'))
    source = destination if destination.exists() else Path(app.get_filename())
    data = key_file(source)
    group = 'Desktop Entry'
    if not has_key(data, group, 'X-ADWS-Original-Exec'):
        data.set_string(group, 'X-ADWS-Original-Exec', data.get_string(group, 'Exec'))
        data.set_boolean(group, 'X-ADWS-Original-Local', destination.exists())
    command = data.get_string(group, 'X-ADWS-Original-Exec')
    if has_key(data, group, 'DBusActivatable') and not has_key(data, group, 'X-ADWS-Original-DBusActivatable'):
        data.set_boolean(group, 'X-ADWS-Original-DBusActivatable', data.get_boolean(group, 'DBusActivatable'))
    data.set_boolean(group, 'DBusActivatable', False)
    data.set_string(group, 'Exec', scaling_command(command, factor, engine))
    # Desktop actions (new window/private window) should use the same scale.
    for section in data.get_groups()[0]:
        if section.startswith('Desktop Action ') and has_key(data, section, 'Exec'):
            if not has_key(data, section, 'X-ADWS-Original-Exec'):
                data.set_string(section, 'X-ADWS-Original-Exec', data.get_string(section, 'Exec'))
            data.set_string(section, 'Exec', scaling_command(data.get_string(section, 'X-ADWS-Original-Exec'), factor, engine))
    data.set_double(group, 'X-ADWS-Scale', float(factor))
    data.set_string(group, 'X-ADWS-Scale-Engine', engine)
    replace_files({destination: data.to_data()[0].encode()})


def restore(app):
    destination = local_directory()/identity(app)
    if destination.is_symlink() or not destination.exists():
        return
    data = key_file(destination)
    if not has_key(data, 'Desktop Entry', 'X-ADWS-Original-Exec'):
        return
    for group in data.get_groups()[0]:
        if has_key(data, group, 'X-ADWS-Original-Exec'):
            data.set_string(group, 'Exec', data.get_string(group, 'X-ADWS-Original-Exec'))
            data.remove_key(group, 'X-ADWS-Original-Exec')
    if has_key(data, 'Desktop Entry', 'X-ADWS-Original-DBusActivatable'):
        data.set_boolean('Desktop Entry', 'DBusActivatable', data.get_boolean('Desktop Entry', 'X-ADWS-Original-DBusActivatable'))
        data.remove_key('Desktop Entry', 'X-ADWS-Original-DBusActivatable')
    else:
        data.remove_key('Desktop Entry', 'DBusActivatable')
    for key in ('X-ADWS-Original-Local', 'X-ADWS-Scale', 'X-ADWS-Scale-Engine'):
        data.remove_key('Desktop Entry', key)
    # Keep the entry: it may contain other user edits made after scaling.
    replace_files({destination: data.to_data()[0].encode()})


def build_card(host):
    from adws_system_settings import card, label
    from adws_settings_widgets import ApplicationChoice
    box = card('应用缩放', '为指定应用设置启动缩放。完全退出应用后重新打开生效；不会改变系统缩放。')
    chooser = ApplicationChoice('application/octet-stream')
    chooser.set_active(-1)
    factor = Gtk.SpinButton.new_with_range(50, 400, 5)
    factor.set_value(170)
    engine = Gtk.ComboBoxText()
    engine.append('qt', 'Qt / WPS'); engine.append('electron', 'Chromium / Electron / 飞书')
    engine.set_active(0)
    for title, widget in [('应用', chooser), ('缩放 (%)', factor), ('应用类型', engine)]:
        box.pack_start(host.config.row_widget(tr(title), widget), False, False, 0)
    message = label('', 'dim-label')
    actions = Gtk.Box(spacing=8)
    def selected(*_):
        app = chooser.get_app_info()
        if not app: return
        command = (app.get_commandline() or '').lower()
        engine.set_active_id('electron' if any(n in command for n in ('feishu', 'chrome', 'chromium', 'electron', 'code', 'discord')) else 'qt')
        try:
            data = key_file(local_directory()/identity(app))
            factor.set_value(data.get_double('Desktop Entry', 'X-ADWS-Scale')*100)
            engine.set_active_id(data.get_string('Desktop Entry', 'X-ADWS-Scale-Engine'))
        except (GLib.Error, ValueError): pass
    chooser.connect('changed', selected)
    def perform(reset):
        app = chooser.get_app_info()
        if not app: return
        try:
            restore(app) if reset else save(app, factor.get_value()/100, engine.get_active_id())
            message.set_text(tr('已保存，请完全退出应用后重新打开。'))
        except Exception as exc: message.set_text(str(exc))
    for title, reset in [('保存应用缩放', False), ('恢复原始启动命令', True)]:
        button = Gtk.Button(label=tr(title)); button.connect('clicked', lambda _, reset=reset: perform(reset))
        actions.pack_start(button, False, False, 0)
    box.pack_start(actions, False, False, 0); box.pack_start(message, False, False, 0)
    return box

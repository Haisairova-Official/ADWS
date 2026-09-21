#!/usr/bin/env python3
"""Launch a taskbar application's registered desktop entry, without a shell."""
import argparse
import logging
import os
import re
import shutil
import subprocess
import json
import fcntl
import tempfile
from pathlib import Path

from gi.repository import Gio, GLib
from mnws_i18n import tr as _tr

LOG = logging.getLogger('mnws-app-launch')


def pin_application(app_id, enabled):
    directory = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'mnws'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'taskbar-pins.json'
    normalize = lambda value: value.removesuffix('.desktop').casefold()
    info = resolve_app(app_id) if enabled else None
    desktop_id = info.get_id() if info else app_id
    with (directory / '.taskbar-pins.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {'version': 1, 'apps': []}
        if (not isinstance(data, dict) or data.get('version') != 1
                or not isinstance(data.get('apps'), list)
                or any(not isinstance(pin, dict) or any(not isinstance(pin.get(key), str)
                       or not pin[key] for key in ('app_id', 'desktop_id', 'name')) for pin in data['apps'])):
            raise ValueError(_tr('固定应用配置无效，请检查 taskbar-pins.json。'))
        aliases = {normalize(app_id), normalize(desktop_id)}
        matches = lambda pin: bool(aliases & {normalize(pin['app_id']), normalize(pin['desktop_id'])})
        if enabled:
            if any(matches(pin) for pin in data['apps']):
                return
            data['apps'].append({'app_id': app_id, 'desktop_id': desktop_id, 'name': info.get_name()})
        else:
            data['apps'] = [pin for pin in data['apps'] if not matches(pin)]
        fd, name = tempfile.mkstemp(prefix='.taskbar-pins-', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    LOG.info('%s: %s', 'pin' if enabled else 'unpin', app_id)


def resolve_app(app_id):
    if not app_id or '/' in app_id or '\x00' in app_id:
        raise ValueError(_tr('无法找到此窗口对应的应用启动器。'))
    desktop_id = app_id if app_id.endswith('.desktop') else app_id + '.desktop'
    try:
        info = Gio.DesktopAppInfo.new(desktop_id)
    except TypeError:  # PyGObject raises for a NULL constructor result on some versions.
        info = None
    if info and not info.get_is_hidden():
        return info
    normalized = app_id.removesuffix('.desktop').casefold()
    matches = []
    for app in Gio.AppInfo.get_all():
        if not isinstance(app, Gio.DesktopAppInfo) or app.get_is_hidden():
            continue
        if (app.get_id() or '').removesuffix('.desktop').casefold() == normalized:
            return app
        if (app.get_startup_wm_class() or '').casefold() == normalized:
            matches.append(app)
    # Do not guess between unrelated launchers with the same window class.
    if len(matches) == 1:
        return matches[0]
    raise ValueError(_tr('无法找到此窗口对应的应用启动器。'))


def admin_argv(info):
    if info.get_boolean('Terminal') or info.get_string('X-Flatpak') or info.get_string('X-SnapInstanceName'):
        raise ValueError(_tr('此应用不支持从任务栏以管理员权限启动。'))
    command = info.get_string('Exec') or ''
    if not command:
        raise ValueError(_tr('此应用不支持从任务栏以管理员权限启动。'))
    _, arguments = GLib.shell_parse_argv(command)
    result = []
    for token in arguments:
        if token in ('%f', '%F', '%u', '%U', '%d', '%D', '%n', '%N', '%v', '%m'):
            continue
        if token == '%i':
            icon = info.get_string('Icon')
            if icon:
                result.extend(['--icon', icon])
            continue
        def expand(match):
            code = match.group(1)
            if code == '%':
                return '%'
            if code == 'c':
                return info.get_name()
            if code == 'k':
                return info.get_filename() or ''
            if code and code in 'fudDnNvm':
                return ''
            raise ValueError(_tr('应用启动命令包含不支持的占位符。'))
        result.append(re.sub(r'%(.)?', expand, token))
    executable = shutil.which(result[0]) if result else None
    if not executable:
        raise ValueError(_tr('应用程序不存在或不可执行。'))
    result[0] = executable
    pkexec = shutil.which('pkexec')
    if not pkexec:
        raise ValueError(_tr('未安装 pkexec，请安装 polkit 并启用系统认证代理。'))
    # pkexec authenticates first; only display connection variables cross the boundary.
    # Never carry the user's HOME, session bus or interpreter/library search paths.
    display = [f'{key}={os.environ[key]}' for key in
               ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR')
               if os.environ.get(key)]
    return [pkexec, '--disable-internal-agent', '/usr/bin/env', *display, *result]


def launch(app_id, administrator=False):
    info = resolve_app(app_id)
    LOG.info('%s: %s', 'administrator' if administrator else 'new-window', info.get_id())
    if administrator:
        # This helper waits, never Waybar's GTK thread. No password enters MNWS.
        completed = subprocess.run(admin_argv(info), cwd=info.get_string('Path') or None,
                                   stderr=subprocess.PIPE, text=True)
        if completed.returncode == 126:  # Authentication dismissed.
            return
        if completed.returncode:
            LOG.error('Administrator launch exit=%s: %s', completed.returncode, completed.stderr)
            raise RuntimeError(_tr('管理员启动失败。请检查系统认证代理，以及此应用是否支持管理员运行。'))
        return
    actions = info.list_actions()
    action = next((action for action in actions
                   if action.casefold().replace('_', '-').replace(' ', '-') in
                   ('new-window', 'newwindow')), None)
    context = Gio.AppLaunchContext()
    if action:
        info.launch_action(action, context)
    else:
        info.launch([], context)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('app_id')
    parser.add_argument('--administrator', action='store_true')
    pin_options = parser.add_mutually_exclusive_group()
    pin_options.add_argument('--pin', action='store_true')
    pin_options.add_argument('--unpin', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        if args.pin or args.unpin:
            pin_application(args.app_id, args.pin)
        else:
            launch(args.app_id, args.administrator)
    except (ValueError, RuntimeError, OSError, GLib.Error) as exc:
        LOG.error('%s', exc)
        from mnws_i18n import prepare_gtk_language
        prepare_gtk_language()
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.CLOSE,
                                   text=_tr('无法启动应用'))
        dialog.format_secondary_text(str(exc))
        dialog.run()
        dialog.destroy()
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

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
import threading
from pathlib import Path

from gi.repository import Gio, GLib
from adws_i18n import tr as _tr

LOG = logging.getLogger('adws-app-launch')


def pin_application(app_id, enabled):
    directory = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'adws'
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
    # The administrative process keeps pkexec's own HOME/runtime environment.
    # A relative Wayland name depends on the user's runtime directory; make
    # only the display socket absolute instead of exporting that directory.
    display = []
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY'):
        value = os.environ.get(key)
        if not value:
            continue
        if key == 'WAYLAND_DISPLAY' and not os.path.isabs(value):
            runtime = os.environ.get('XDG_RUNTIME_DIR')
            if not runtime or not os.path.isabs(runtime):
                raise ValueError(_tr('无法确定 Wayland 显示连接，请在图形会话中重试。'))
            value = os.path.join(runtime, value)
        display.append(f'{key}={value}')
    return [pkexec, '--disable-internal-agent', '/usr/bin/env', *display, *result]


def administrator_error(info, stderr, code):
    summary = _tr('无法以管理员权限启动“%s”。') % info.get_name()
    details = (stderr or '').strip()[-4096:]
    if code == 127:
        summary += '\n' + _tr('系统未完成授权，请检查认证代理或重试。')
    elif any(text in details.lower() for text in ('as root', 'with sudo', '--no-sandbox', 'not supported')):
        summary += '\n' + _tr('此应用拒绝管理员运行，请使用普通方式启动。')
    if details:
        summary += '\n\n' + _tr('应用返回：') + '\n' + details
    return summary


def run_administrator(argv, cwd=None, app_name=None):
    # This process owns the auth agent, never Waybar's GTK thread. Scope it to
    # the pkexec caller so it cannot take over unrelated session requests.
    from adws_i18n import prepare_gtk_language
    prepare_gtk_language()
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    GLib.set_prgname('adws-config')
    host = Gtk.Window()
    host.authorization_app_name = app_name
    agent = None
    try:
        try:
            from adws_native_auth import start
            agent = start(host, process_only=True)
        except (ImportError, ValueError) as error:
            LOG.warning('Native authorization agent unavailable: %s', error)
        results = []
        loop = GLib.MainLoop()
        def completed(result):
            results.append(result)
            loop.quit()
            return False
        def work():
            try:
                # Long-running GUI apps can emit unlimited diagnostics. Keep
                # them out of RAM and show only their final, bounded output.
                with tempfile.TemporaryFile() as errors:
                    result = subprocess.run(argv, cwd=cwd, stderr=errors)
                    errors.seek(0, os.SEEK_END)
                    size = errors.tell()
                    errors.seek(max(0, size - 4096))
                    result.stderr = errors.read().decode('utf-8', errors='replace')
            except Exception as error:
                result = error
            GLib.idle_add(completed, result)
        threading.Thread(target=work, daemon=True).start()
        loop.run()
        if isinstance(results[0], Exception):
            raise results[0]
        return results[0]
    finally:
        if agent is not None:
            agent.close()
        host.destroy()


def launch(app_id, administrator=False):
    info = resolve_app(app_id)
    LOG.info('%s: %s', 'administrator' if administrator else 'new-window', info.get_id())
    if administrator:
        completed = run_administrator(admin_argv(info), cwd=info.get_string('Path') or None,
                                      app_name=info.get_name())
        if completed.returncode == 126:  # Authentication dismissed.
            return
        if completed.returncode:
            LOG.error('Administrator launch exit=%s: %s', completed.returncode, completed.stderr)
            raise RuntimeError(administrator_error(info, completed.stderr, completed.returncode))
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
        from adws_i18n import prepare_gtk_language
        prepare_gtk_language()
        import gi
        gi.require_version('Gtk', '3.0')
        GLib.set_prgname('adws-config')
        from adws_launch_dialogs import show_launch_error
        show_launch_error(str(exc))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Start the icon layer as an independent, transient systemd user service."""
from .i18n import tr as _tr
from pathlib import Path
import os
import sys
import time

from gi.repository import Gio, GLib

UNIT = "niri-desktop-layer.service"
APP_ID = "io.github.akizuki.NiriDesktopLayer"


def start_service(call, properties, unit=UNIT):
    """Reuse the same loaded unit; wait for a previous stop to finish."""
    manager = "/org/freedesktop/systemd1"
    interface = "org.freedesktop.systemd1.Manager"
    deadline = time.monotonic() + 5
    requested = dict(properties)["ExecStart"].unpack()
    while True:
        try:
            return call(manager, interface, "StartTransientUnit",
                        GLib.Variant("(ssa(sv)a(sa(sv)))", (unit, "fail", properties, [])))
        except GLib.Error as error:
            if Gio.DBusError.get_remote_error(error) != "org.freedesktop.systemd1.UnitExists":
                raise
            try:
                path = call(manager, interface, "GetUnit", GLib.Variant("(s)", (unit,)))[0]
                def get(iface, name):
                    return call(path, "org.freedesktop.DBus.Properties", "Get",
                                GLib.Variant("(ss)", (iface, name)))[0]
                state = get("org.freedesktop.systemd1.Unit", "ActiveState")
                if state not in ("deactivating", "activating"):
                    commands = get("org.freedesktop.systemd1.Service", "ExecStart")
                    # ExecStart from systemd includes exit timestamps/status fields.
                    actual = [(row[0], list(row[1]), row[2]) for row in commands]
                    expected = [(row[0], list(row[1]), row[2]) for row in requested]
                    if actual != expected:
                        raise RuntimeError("Existing desktop service uses a different command; refusing to start it.")
                    return call(manager, interface, "StartUnit", GLib.Variant("(ss)", (unit, "fail")))
            except GLib.Error as lookup_error:
                if Gio.DBusError.get_remote_error(lookup_error) != "org.freedesktop.systemd1.NoSuchUnit":
                    raise
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for the previous desktop service to stop.") from error
            time.sleep(.1)


def main():
    root = Path(__file__).resolve().parent.parent
    executable = str(root / "desktop-layer")
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        def call(path, interface, method, args):
            return bus.call_sync("org.freedesktop.systemd1", path, interface, method,
                                 args, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()
        owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                              GLib.Variant("(s)", (APP_ID,)), None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        if owner:
            print(_tr('桌面图标层已经运行。'))
            return 0
        args = [executable, "--state", str(root / "state/layout.json"), *sys.argv[1:]]
        tools = root.parents[1] / 'tools'
        if str(tools) not in sys.path: sys.path.insert(0, str(tools))
        from adws_runtime import taskbar_environment
        session_env = taskbar_environment()
        environment = [f"{key}={session_env[key]}" for key in (
            "WAYLAND_DISPLAY", "NIRI_SOCKET", "XDG_CURRENT_DESKTOP", "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "XAUTHORITY", "LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "PATH",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME") if key in session_env]
        properties = [
            ("Description", GLib.Variant("s", "Niri desktop icons")),
            ("Type", GLib.Variant("s", "exec")),
            ("Restart", GLib.Variant("s", "no")),
            # Applications launched from the desktop must survive its restart.
            # Owned widget workers are stopped by their explicit host lifecycle.
            ("KillMode", GLib.Variant("s", "process")),
            ("CollectMode", GLib.Variant("s", "inactive-or-failed")),
            ("ExecStart", GLib.Variant("a(sasb)", [(executable, args, False)])),
            ("Environment", GLib.Variant("as", environment)),
        ]
        start_service(call, properties)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                  GLib.Variant("(s)", (APP_ID,)), None, Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
            if owner:
                print(_tr('桌面图标层已独立启动，关闭终端或 Codex 不会结束它。'))
                return 0
            time.sleep(.1)
        print(''.join([_tr('服务已提交，但图标层尚未就绪。查看日志：journalctl --user -u '), f'{UNIT}', ' -n 30']), file=sys.stderr)
        return 1
    except (GLib.Error, RuntimeError) as error:
        print(''.join([_tr('无法启动独立服务：'), f'{error}']), file=sys.stderr)
        return 1

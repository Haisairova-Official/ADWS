"""Start the icon layer as an independent, transient systemd user service."""
from .i18n import tr as _tr
from pathlib import Path
import os
import sys
import time

from gi.repository import Gio, GLib

UNIT = "niri-desktop-layer.service"
APP_ID = "io.github.akizuki.NiriDesktopLayer"


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
        environment = [f"{key}={os.environ[key]}" for key in (
            "WAYLAND_DISPLAY", "NIRI_SOCKET", "XDG_CURRENT_DESKTOP", "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "XAUTHORITY", "LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "PATH",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME") if key in os.environ]
        properties = [
            ("Description", GLib.Variant("s", "Niri desktop icons")),
            ("Type", GLib.Variant("s", "exec")),
            ("Restart", GLib.Variant("s", "no")),
            ("CollectMode", GLib.Variant("s", "inactive-or-failed")),
            ("ExecStart", GLib.Variant("a(sasb)", [(executable, args, False)])),
            ("Environment", GLib.Variant("as", environment)),
        ]
        call("/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager", "StartTransientUnit",
             GLib.Variant("(ssa(sv)a(sa(sv)))", (UNIT, "fail", properties, [])))
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
    except GLib.Error as error:
        print(''.join([_tr('无法启动独立服务：'), f'{error.message}']), file=sys.stderr)
        return 1

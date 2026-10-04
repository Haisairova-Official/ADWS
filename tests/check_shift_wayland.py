#!/usr/bin/env python3
"""Drive native Shift menus through real, isolated Wayland input.

Build native tests first, then run under dbus-run-session. Requires niri,
Xvfb, xdotool, PyGObject and gtk-layer-shell; never sends input to the desktop.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def main():
    repo = Path(__file__).resolve().parents[1]
    binaries = [p for p in (repo / "src/niri-taskbar/target/debug/deps").glob("niri_taskbar-*")
                if p.is_file() and os.access(p, os.X_OK) and p.suffix == ""]
    if not binaries:
        raise RuntimeError("Build native tests with cargo test --lib --no-run first")
    binary = max(binaries, key=lambda p: p.stat().st_mtime)
    with tempfile.TemporaryDirectory(prefix="adws-wayland-shift-") as temp:
        root = Path(temp)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        config = root / "config.kdl"
        config.write_text('animations { off; }\ninput { keyboard { xkb { layout "us"; }; }; }\n')
        processes = []
        niri = None
        env = None
        connection = None
        logs = []

        def wait_for(predicate, timeout=10):
            deadline = time.monotonic() + timeout
            while not predicate():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timed out waiting for nested Wayland test")
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("A nested test process exited early")
                time.sleep(0.03)

        def xdo(*args):
            return subprocess.check_output(["xdotool", *args], env=env, timeout=5).decode().strip()

        def phase(name):
            wait_for(lambda: (root / "phase").exists() and (root / "phase").read_text() == name)
            print(name, flush=True)

        try:
            xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1280x800x24"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            processes.append(xvfb)
            display = ":" + xvfb.stdout.readline().decode().strip()
            env = {**os.environ, "DISPLAY": display, "XDG_RUNTIME_DIR": str(runtime),
                   "LIBGL_ALWAYS_SOFTWARE": "1", "WINIT_UNIX_BACKEND": "x11"}
            for key in ("WAYLAND_DISPLAY", "NIRI_SOCKET", "GDK_BACKEND", "HYPRLAND_INSTANCE_SIGNATURE"):
                env.pop(key, None)
            compositor_log = root / "niri.log"
            logs.append(compositor_log)
            with compositor_log.open("w") as output:
                niri = subprocess.Popen(["niri", "--config", str(config)], env=env,
                                        stdout=output, stderr=output, start_new_session=True)
            processes.append(niri)
            wait_for(lambda: any(p.is_socket() for p in runtime.glob("wayland-*")))
            socket = next(p for p in runtime.glob("wayland-*") if p.is_socket())
            client = {**env, "WAYLAND_DISPLAY": socket.name, "GDK_BACKEND": "wayland",
                      "ADWS_SHIFT_TEST_DIR": str(root), "GIO_USE_VFS": "local"}
            dummy = subprocess.Popen([sys.executable, "-c",
                "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; "
                "w=Gtk.Window(title='typing'); w.add(Gtk.Entry()); w.show_all(); Gtk.main()"],
                env=client, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(dummy)
            time.sleep(0.3)
            test_log = root / "native.log"
            logs.append(test_log)
            with test_log.open("w") as output:
                test = subprocess.Popen([str(binary), "button::action_tests::wayland_layer_shift_menu",
                    "--exact", "--ignored", "--nocapture", "--test-threads=1"],
                    env=client, stdout=output, stderr=output)
            processes.append(test)
            wait_for(lambda: (root / "ready.json").exists())
            ready = json.loads((root / "ready.json").read_text())
            host = xdo("search", "--name", "^niri$").splitlines()[0]
            geometry = dict(line.split("=", 1) for line in xdo("getwindowgeometry", "--shell", host).splitlines())
            xdo("windowfocus", host)

            xlib = ctypes.CDLL("libX11.so.6")
            xtst = ctypes.CDLL("libXtst.so.6")
            xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            xlib.XOpenDisplay.restype = ctypes.c_void_p
            xlib.XFlush.argtypes = [ctypes.c_void_p]
            xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
            xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
            connection = xlib.XOpenDisplay(display.encode())
            assert connection

            def move(card):
                x, y = ready[card]
                xtst.XTestFakeMotionEvent(connection, -1, int(geometry["X"]) + x,
                    int(geometry["Y"]) + int(geometry["HEIGHT"]) - ready["height"] + y, 0)
                xlib.XFlush(connection)
                time.sleep(0.2)

            card = "single"
            move(card)
            xdo("keydown", "Shift_L")
            xdo("click", "3")
            phase(f"{card}-shift")
            xdo("keyup", "Shift_L")
            phase(f"{card}-close")
            xdo("keydown", "Shift_R")
            phase(f"{card}-repress")
            xdo("keyup", "Shift_R")
            xdo("key", "Escape")
            test.wait(timeout=10)
            if test.returncode:
                raise RuntimeError("Native Wayland regression failed")
            assert (root / "phase").read_text() == f"{card}-restored"
            print(test_log.read_text())
        except Exception:
            for log in logs:
                print(f"{log.name}:\n{log.read_text()[-6000:]}", file=sys.stderr)
            raise
        finally:
            if env and processes[0].poll() is None:
                try:
                    xdo("keyup", "Shift_L", "Shift_R")
                except subprocess.SubprocessError:
                    pass
            if connection:
                xlib.XCloseDisplay(connection)
            for process in reversed(processes):
                if process.poll() is None:
                    if process is niri:
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()

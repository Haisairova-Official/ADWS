#!/usr/bin/env python3
"""Exercise the opt-in native bar, real plugins and desktop in a private Niri session."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
NATIVE = "adws-taskbar-preview"


def wait_for(description, check, timeout=12):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if result := check():
            return result
        time.sleep(0.06)
    raise RuntimeError(f"Timed out waiting for {description}")


def child_environment(root):
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ADWS_", "DBUS_", "XDG_", "NIRI_", "WAYLAND_"))
           and k not in ("DISPLAY", "GDK_BACKEND", "HYPRLAND_INSTANCE_SIGNATURE", "DESKTOP_STARTUP_ID")}
    locales = subprocess.check_output(["locale", "-a"], text=True).splitlines()
    env.update({
        "HOME": str(root), "XDG_RUNTIME_DIR": str(runtime), "XDG_CONFIG_HOME": str(root / ".config"),
        "XDG_CACHE_HOME": str(root / ".cache"), "XDG_STATE_HOME": str(root / ".local/state"),
        "XDG_DATA_HOME": str(root / ".local/share"), "ADWS_PLUGIN_DIR": str(root / "plugins"),
        "PULSE_SERVER": "unix:" + str(runtime / "test-pulse"), "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent",
        "GSETTINGS_BACKEND": "memory", "GIO_USE_VFS": "local", "NO_AT_BRIDGE": "1",
        "WINIT_UNIX_BACKEND": "x11", "LIBGL_ALWAYS_SOFTWARE": "1", "GTK_IM_MODULE": "simple",
        "LC_ALL": "zh_CN.UTF-8" if "zh_CN.utf8" in locales else "C.UTF-8",
        "ADWS_LOG_LEVEL": "1", "ADWS_TASKBAR_TIMING": "1", "TMPDIR": str(root),
    })
    return env


def fixture(root, env, task_library):
    library = root / ".local/lib/waybar"
    library.mkdir(parents=True)
    (library / "libniri_taskbar.so").symlink_to(task_library.resolve(strict=True))
    for name in ("libadws_panel.so", "libwaybar-space.so"):
        (library / name).symlink_to((ROOT / "libexec/taskbar-preview" / name).resolve(strict=True))
    plugins = Path(env["ADWS_PLUGIN_DIR"])
    plugins.mkdir()
    for source in ("examples/hello-panel", "netease-lyrics"):
        subprocess.run([sys.executable, str(ROOT / "tools/adws_plugin.py"), "build",
                        str(ROOT / "plugins" / source), "-o", str(plugins / (source.split("/")[-1] + ".mplg"))],
                       check=True, env=env, stdout=subprocess.DEVNULL)
    layout = json.loads((ROOT / "config/taskbar-layout.json").read_text())
    layout["builtins"] += [
        dict(id="workspaces", instance="workspaces", slot="left", order=2, enabled=True),
        dict(id="sidebar", instance="sidebar", slot="right", order=3, enabled=True),
    ]
    layout["builtins"][5]["order"] = 4  # clock at the outer edge
    layout["options"].update(start_launcher_mode="adws", start_label="开始", taskbar_library=str(task_library.resolve()))
    layout["plugins"] = [
        dict(package="org.adws.hello", instance="hello", slot="right", order=-1, enabled=True),
        dict(package="org.AkiACG_Community.NCMLyricsBar", instance="lyrics", slot="center", order=0,
             width=220, enabled=True),
    ]
    path = root / "layout.json"
    path.write_text(json.dumps(layout))
    return path


def exercise(root, binary, task_library, screenshot):
    env = child_environment(root)
    layout = fixture(root, env, task_library)
    children = []

    def start(name, args, **kwargs):
        with (root / (name + ".log")).open("w") as log:
            proc = subprocess.Popen(args, env=env, stderr=log, stdout=kwargs.pop("stdout", log),
                                    start_new_session=True, **kwargs)
        children.append(proc)
        return proc

    def run(*args):
        return subprocess.check_output(args, env=env, text=True, timeout=8)

    def layers():
        return {item["namespace"] for item in json.loads(run("niri", "msg", "-j", "layers"))}

    try:
        bus = start("dbus", ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                    stdout=subprocess.PIPE, text=True)
        env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
        xvfb = start("xvfb", ["Xvfb", "-displayfd", "1", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                     stdout=subprocess.PIPE, text=True)
        env["DISPLAY"] = ":" + xvfb.stdout.readline().strip()
        config = root / "niri.kdl"
        pid_file = root / "waybar.pid"
        shortcut = root / "hide-waybar.py"
        shortcut.write_text("import os, signal\nfrom pathlib import Path\n"
                            + f"os.kill(int(Path({str(pid_file)!r}).read_text()), signal.SIGTERM)\n")
        config.write_text('hotkey-overlay { skip-at-startup; }\nanimations { off; }\n'
                          'window-rule { match title="ADWS"; open-floating true; }\n'
                          + 'binds { Super+F4 { spawn "' + sys.executable + '" "' + str(shortcut) + '"; }; }\n')
        start("niri", ["niri", "--config", str(config)])
        runtime = Path(env["XDG_RUNTIME_DIR"])
        ipc = wait_for("private compositor", lambda: next(runtime.glob("niri.*.sock"), None))
        display = next(p for p in runtime.glob("wayland-*") if p.is_socket() and not p.name.endswith("-agent"))
        env.update(NIRI_SOCKET=str(ipc), WAYLAND_DISPLAY=display.name, GDK_BACKEND="wayland", XDG_CURRENT_DESKTOP="niri")
        desk = root / "Desktop"
        desk.mkdir()
        (desk / "ADWS.txt").write_text("ADWS")
        start("desktop", [sys.executable, str(ROOT / "src/niri-desktop-layer/desktop-layer"),
                          "--directory", str(desk), "--state", str(root / "icons.json")])
        wait_for("desktop layer", lambda: "niri-desktop-layer" in layers())
        top_config = root / "top.json"
        top_config.write_text(json.dumps({"position": "top", "modules-center": ["clock"], "clock": {"format": "{:%H:%M}"}}))
        top_css = root / "top.css"
        top_css.write_text("window#waybar {background: #252933; color: white;}")
        top = start("waybar", ["waybar", "-c", str(top_config), "-s", str(top_css)])
        pid_file.write_text(str(top.pid))
        wait_for("independent Waybar", lambda: "waybar" in layers())
        launcher = start("preview", ["bash", str(ROOT / "adws"), "taskbar-preview", "--current-session", "--layout", str(layout),
                                     "--config", str(ROOT / "config/waybar/config-bottom.jsonc"),
                                     "--style", str(ROOT / "config/waybar/style-bottom.css"), "--binary", str(binary)])
        wait_for("native and Waybar together", lambda: {NATIVE, "waybar", "niri-desktop-layer"} <= layers())
        def host_pid():
            for child in Path(f"/proc/{launcher.pid}/task/{launcher.pid}/children").read_text().split():
                if Path(f"/proc/{child}/exe").resolve() == binary:
                    return int(child)
        pid = wait_for("native host PID", host_pid)
        def snapshots_ready():
            snapshots = {}
            for snap in Path(temp_folder).rglob("plugin-preview/*.json"):
                try:
                    entry = json.loads(snap.read_text())
                    snapshots[entry["instance"]] = entry
                except (OSError, KeyError, ValueError):
                    continue
            return set(snapshots) >= {"lyrics", "hello"} and all(s.get("class") != "error" for s in snapshots.values())
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        temp_folder = Path(os.fsdecode(args[args.index(b"--config") + 1])).parent
        wait_for("JSON and two-row lyric plugin output", snapshots_ready, 20)
        # Deliver the real shortcut to the nested session. Its binding targets
        # the private test PID, so even a failed test cannot signal a live bar.
        host = run("xdotool", "search", "--name", "^niri$").splitlines()[0]
        run("xdotool", "windowfocus", host)
        run("xdotool", "key", "Super_L+F4")
        top.wait(timeout=5)
        # Use the settings reload entry point with the host's private XDG tree.
        # A new plugin-runner PID and a fresh snapshot prove remount completed.
        private_env = dict(entry.split("=", 1) for entry in Path(f"/proc/{pid}/environ").read_bytes().decode().split("\0") if "=" in entry)
        target = Path(private_env["XDG_CONFIG_HOME"]) / "waybar/config-bottom.jsonc"
        editor_input = json.loads(target.read_text())
        editor_input["clock"]["format"] = "{:%H:%M:%S}"
        target.write_text(json.dumps(editor_input))
        snapshot = next(f for f in temp_folder.rglob("plugin-preview/*.json") if json.loads(f.read_text())["instance"] == "lyrics")
        old_writer = json.loads(snapshot.read_text())["pid"]
        subprocess.run([sys.executable, "-c",
                        "from adws_native_taskbar import reload_preview; ok, message = reload_preview(); print(message); raise SystemExit(int(not ok))"],
                       cwd=ROOT / "tools", env=private_env, check=True, timeout=5)
        def remounted():
            try:
                return json.loads(snapshot.read_text())["pid"] != old_writer
            except (FileNotFoundError, KeyError, ValueError):
                return False
        wait_for("settings reload remounted the lyric plugin", remounted)

        wait_for("Waybar removed independently", lambda: "waybar" not in layers() and NATIVE in layers())
        os.kill(pid, signal.SIGUSR1)
        wait_for("native hide", lambda: NATIVE not in layers())
        os.kill(pid, signal.SIGUSR1)
        wait_for("native show", lambda: NATIVE in layers())
        test_window = start("client", [sys.executable, "-c",
            "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk, GLib; "
            "GLib.set_prgname('org.gnome.TextEditor'); "
            "w=Gtk.Window(title='ADWS'); w.set_default_size(420,185); "
            "w.add(Gtk.Label(label='ADWS  ·  Niri')); w.show_all(); Gtk.main()"])
        wait_for("application window", lambda: any(w["title"] == "ADWS" for w in json.loads(run("niri","msg","-j","windows"))))
        time.sleep(0.6)
        if screenshot:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            run("niri", "msg", "action", "screenshot-screen", "--show-pointer", "false", "--path", str(screenshot))
            wait_for("screenshot", lambda: screenshot.is_file() and screenshot.stat().st_size > 1024)
        geometry = dict(line.split("=", 1) for line in run("xdotool", "getwindowgeometry", "--shell", host).splitlines())
        run("xdotool", "windowfocus", host)
        def click(x, y):
            run("xdotool", "mousemove", "--window", host, str(x), str(y))
            time.sleep(.15)
            run("xdotool", "click", "1")
        click(36, int(geometry["HEIGHT"])-23)
        wait_for("start menu after Waybar exited", lambda: "adws-start-menu" in layers())
        # The layer can be listed before the compositor grants keyboard focus.
        # Click a point on the dismiss surface outside the bottom-left menu.
        wait_for("menu dismiss surface", lambda: "adws-start-dismiss" in layers())
        click(int(geometry["WIDTH"])-15, 12)
        wait_for("menu dismissal", lambda: "adws-start-menu" not in layers())
        click(int(geometry["WIDTH"])-45, int(geometry["HEIGHT"])-23)
        wait_for("clock control center", lambda: "launcher" in layers())
        run("xdotool", "key", "Escape")
        second_window = start("second-client", [sys.executable, "-c",
            "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk, GLib; "
            "GLib.set_prgname('org.adws.Second'); w=Gtk.Window(title='Second'); w.show_all(); Gtk.main()"])
        def focused_title():
            window = json.loads(run("niri", "msg", "-j", "focused-window"))
            return window["title"] if window else None
        wait_for("second window focused", lambda: focused_title() == "Second")
        click(92, int(geometry["HEIGHT"])-23)
        wait_for("focus from window card", lambda: focused_title() == "ADWS")
        second_window.terminate()
        test_window.terminate()
        launcher.terminate()
        launcher.wait(timeout=8)
        wait_for("clean shutdown", lambda: NATIVE not in layers() and not temp_folder.exists())
        # A two-row plugin used to recreate its health directory after cleanup.
        time.sleep(.4)
        if temp_folder.exists():
            raise RuntimeError("A late plugin write recreated the trial directory")
        if "niri-desktop-layer" not in layers():
            raise RuntimeError("Stopping the preview stopped the desktop")
        log = (root / "preview.log").read_text()
        for error in ("panicked at", "Niri taskbar module init failed", "GLib-CRITICAL", "Gtk-CRITICAL"):
            if error in log:
                raise RuntimeError(f"Native runtime diagnostic: {error}")
        print("PASS: desktop, both bars, both plugin interfaces, independent visibility, Start and clock")
    except Exception:
        for log in root.glob("*.log"):
            print(f"{log.name}\n{log.read_text(errors='replace')[-1800:]}", file=sys.stderr)
        raise
    finally:
        for proc in reversed(children):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "libexec/taskbar-preview/adws-taskbar")
    parser.add_argument("--task-library", type=Path, default=ROOT / "libexec/taskbar-preview/libniri_taskbar.so")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="adws-native-wayland-") as folder:
        exercise(Path(folder), args.binary.resolve(strict=True), args.task_library,
                 args.screenshot.resolve() if args.screenshot else None)

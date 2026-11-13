"""Own the private compositor, session bus, and native bar for a windowed preview."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def run_nested(command, env, directory):
    niri = shutil.which('niri', path=env.get('PATH'))
    bus = shutil.which('dbus-daemon', path=env.get('PATH'))
    if not niri or not bus:
        raise ValueError('The nested taskbar preview needs niri and dbus-daemon.')
    server_env = dict(env)
    wayland = env.get('WAYLAND_DISPLAY')
    if wayland:
        socket = Path(wayland)
        if not socket.is_absolute():
            if not env.get('XDG_RUNTIME_DIR'):
                raise ValueError('Cannot locate the parent Wayland display without XDG_RUNTIME_DIR.')
            socket = Path(env['XDG_RUNTIME_DIR']) / socket
        if not socket.is_socket():
            raise ValueError(f'Cannot connect to the parent Wayland display: {socket}')
        server_env.update(WAYLAND_DISPLAY=str(socket), WINIT_UNIX_BACKEND='wayland')
        server_env.pop('DISPLAY', None)
    elif env.get('DISPLAY'):
        server_env['WINIT_UNIX_BACKEND'] = 'x11'
    else:
        raise ValueError('Run the nested preview from a Wayland or X11 desktop.')
    # The compositor uses the parent's display as a client, but its listening
    # sockets, bus and configuration all belong to this window only.
    runtime = directory / 'session'
    runtime.mkdir(mode=0o700)
    address = 'unix:path=' + str(runtime / 'bus')
    server_env.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=address,
                      XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='niri')
    for key in ('NIRI_SOCKET', 'NIRI_CONFIG', 'SWAYSOCK', 'HYPRLAND_INSTANCE_SIGNATURE',
                'WAYLAND_SOCKET', 'WAYLAND_DEBUG', 'GDK_BACKEND', 'DBUS_STARTER_ADDRESS', 'DBUS_STARTER_BUS_TYPE'):
        server_env.pop(key, None)
    kdl = directory / 'preview.kdl'
    kdl.write_text('hotkey-overlay { skip-at-startup; }\n', encoding='utf-8')
    config = Path(command[command.index('--config') + 1])
    bar = json.loads(config.read_text(encoding='utf-8'))
    # A virtual output has no physical connector name. This copy belongs only
    # to the preview; normal launches continue to honor the output selector.
    bar.pop('output', None)
    config.write_text(json.dumps(bar, ensure_ascii=False), encoding='utf-8')

    stopped = None
    def on_signal(number, _frame):
        nonlocal stopped
        stopped = number

    with ExitStack() as owned, selectors.DefaultSelector() as events:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            owned.callback(signal.signal, sig, signal.signal(sig, on_signal))
        read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        owned.callback(os.close, read_fd); owned.callback(os.close, write_fd)
        old_wakeup = signal.set_wakeup_fd(write_fd)
        owned.callback(signal.set_wakeup_fd, old_wakeup)
        events.register(read_fd, selectors.EVENT_READ)

        def start(argv, environ):
            proc = subprocess.Popen(argv, env=environ, start_new_session=True)
            owned.callback(stop_process, proc)
            pid_fd = os.pidfd_open(proc.pid)
            owned.callback(os.close, pid_fd)
            events.register(pid_fd, selectors.EVENT_READ, proc)
            return proc

        session_bus = start([bus, '--session', '--nofork', '--nopidfile', '--address=' + address], server_env)
        compositor = start([niri, '--config', str(kdl)], server_env)
        deadline = time.monotonic() + 15
        while not stopped:
            ipc = next(runtime.glob(f'niri.*.{compositor.pid}.sock'), None)
            if ipc and ipc.is_socket() and (runtime / 'bus').is_socket():
                display = ipc.name[len('niri.'):-len(f'.{compositor.pid}.sock')]
                if (runtime / display).is_socket():
                    break
            if compositor.poll() is not None or session_bus.poll() is not None:
                raise ValueError('The nested Niri window or its session bus exited during startup.')
            if time.monotonic() >= deadline:
                raise ValueError('Timed out waiting for the nested Niri display.')
            events.select(timeout=.05)
        if stopped:
            return 128 + stopped
        client_env = {**server_env, 'WAYLAND_DISPLAY': display, 'NIRI_SOCKET': str(ipc),
                      'GDK_BACKEND': 'wayland', 'GSETTINGS_BACKEND': 'memory'}
        # DISPLAY on the compositor may denote an X11 parent. Children's X11
        # fallback must never put their windows outside the nested preview.
        client_env.pop('DISPLAY', None)
        host = start(command, client_env)
        from adws_native_taskbar import register_host
        register_host(host, client_env, nested=True)
        while not stopped:
            for key, _ in events.select():
                if key.data is None:
                    os.read(read_fd, 4096)
                elif key.data is host or key.data is compositor:
                    code = key.data.wait()
                    if key.data is host and code:
                        # GDK can see the server disconnect a moment before Niri
                        # finishes exiting after its window is closed normally.
                        try:
                            code = compositor.wait(timeout=.4)
                        except subprocess.TimeoutExpired:
                            pass
                    return 128 - code if code < 0 else code
                elif key.data is session_bus:
                    raise ValueError('The nested session bus exited unexpectedly.')
        return 128 + stopped

"""Exercise the actual --nested entry entirely inside a private Xvfb and temporary HOME."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import shlex
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def wait_for(proc, predicate):
    end = time.monotonic() + 20
    while time.monotonic() < end:
        if result := predicate():
            return result
        if proc.poll() is not None:
            raise RuntimeError(f'Process {proc.pid} exited early with {proc.returncode}')
        time.sleep(.05)
    raise RuntimeError('Timed out waiting for the private preview layer')


def session_processes(runtime):
    # Record the actual private bus, compositor, host and activated helpers.
    marker = os.fsencode('XDG_RUNTIME_DIR=' + str(runtime))
    processes = {}
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if marker in (proc / 'environ').read_bytes().split(b'\0'):
                fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
                processes[proc] = fields[19]
        except OSError:
            pass
    return processes


def check_closed(processes):
    deadline = time.monotonic() + 4
    while True:
        remaining = {}
        for proc, identity in processes.items():
            try:
                fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
                if fields[19] == identity and fields[0] != 'Z':
                    remaining[proc] = identity
            except FileNotFoundError:
                pass
        if not remaining:
            return
        if time.monotonic() > deadline:
            raise RuntimeError('Preview descendants still running: ' + str(list(remaining)))
        processes = remaining
        time.sleep(.05)


def run(binary, shot):
    with tempfile.TemporaryDirectory(prefix='adws-test-nested-') as name:
        root = Path(name)
        parent_runtime = root / 'parent'; parent_runtime.mkdir(mode=0o700)
        temp = root / 'scratch'; temp.mkdir()
        env = {'PATH':os.defpath, 'HOME':name, 'XDG_RUNTIME_DIR':str(parent_runtime), 'XDG_CONFIG_HOME':str(root/'cfg'),
               'XDG_CACHE_HOME':str(root/'cache'), 'XDG_DATA_HOME':str(root/'data'), 'XDG_STATE_HOME':str(root/'state'),
               'TMPDIR':str(temp), 'LIBGL_ALWAYS_SOFTWARE':'1','LANG':'C.UTF-8','NO_AT_BRIDGE':'1',
               'DBUS_SYSTEM_BUS_ADDRESS':'unix:path=/nonexistent', 'DBUS_SESSION_BUS_ADDRESS':'unix:path=/nonexistent'}
        config = root / 'bar.json'; config.write_text(json.dumps({'output':'My physical monitor','modules-left':['custom/example'],
            'custom/example': {'format':'ADWS'}, 'modules-right':['clock'], 'clock':{'format':'{:%H:%M}'}}))
        style = root / 'bar.css'; style.write_text('window#waybar {background:#293343;color:white} label {font:16px sans-serif;}')
        xvfb = subprocess.Popen(['Xvfb','-displayfd','1','-screen','0','1024x768x24','-nolisten','tcp'],stdout=subprocess.PIPE,env=env)
        try:
            with xvfb.stdout:
                env['DISPLAY'] = ':' + xvfb.stdout.readline().decode().strip()
            with (root/'preview.log').open('w+') as log:
                launcher = subprocess.Popen([str(ROOT/'adws'),'taskbar-preview','--binary',str(binary),
                    '--config',str(config),'--style',str(style)],env=env,stdout=log,stderr=log)
                try:
                    ipc = wait_for(launcher,lambda:next(temp.glob('adws-taskbar-preview-*/session/niri.*.sock'),None))
                    runtime = ipc.parent; display = ipc.name.split('.')[1]
                    client = {**env,'XDG_RUNTIME_DIR':str(runtime),'WAYLAND_DISPLAY':display,'NIRI_SOCKET':str(ipc),
                              'DBUS_SESSION_BUS_ADDRESS':'unix:path='+str(runtime/'bus')}
                    def layers():
                        command = subprocess.run(['niri','msg','-j','layers'],env=client,capture_output=True,text=True,timeout=2)
                        return command.returncode == 0 and any(s.get('namespace')=='adws-taskbar-preview' for s in json.loads(command.stdout))
                    wait_for(launcher, layers)
                    assert (runtime/'bus').is_socket() and not (parent_runtime/'bus').exists()
                    assert json.loads(config.read_text())['output'] == 'My physical monitor'
                    if shot:subprocess.run(['grim',str(shot)],env=client,check=True,timeout=8)
                    # Invoke the same apply endpoint as the settings window, with
                    # an unmistakable module command run only by the reloaded host.
                    workspace = runtime.parent
                    xdg = workspace / 'config'
                    applied = root / 'mounted-after-settings'
                    definition = json.loads(config.read_text())
                    definition['custom/example'] = {'exec': 'printf active > '+shlex.quote(str(applied))+'; printf Reloaded', 'format':'{}'}
                    (xdg/'waybar/config-bottom.jsonc').write_text(json.dumps(definition))
                    reload_env = {**client, 'XDG_CONFIG_HOME':str(xdg),'ADWS_TASKBAR_PREVIEW':'1',
                                  'ADWS_PLUGIN_RUNTIME_DIR':str(workspace),'PYTHONPATH':str(ROOT/'tools')}
                    reload_script = 'from adws_layout import restart_taskbar; ok,text=restart_taskbar();print(text);raise SystemExit(int(not ok))'
                    subprocess.run([sys.executable, '-c', reload_script],env=reload_env,check=True,timeout=8)
                    wait_for(launcher, lambda: applied.is_file() and applied.read_text()=='active')
                    assert layers() and 'exec' not in json.loads(config.read_text())['custom/example']
                    owners = session_processes(runtime)
                    assert len(owners) >= 3
                    # Nest a second instance in that Wayland window. Its parent
                    # display name is relative to the first runtime directory.
                    inner_scratch = root / 'second'; inner_scratch.mkdir()
                    inner_env = {**client, 'TMPDIR': str(inner_scratch)}
                    inner = subprocess.Popen([str(ROOT/'adws'),'taskbar-preview','--nested','--binary',str(binary),
                        '--config',str(config),'--style',str(style)],env=inner_env,stdout=log,stderr=log)
                    try:
                        ipc2 = wait_for(inner,lambda: next(inner_scratch.glob('adws-taskbar-preview-*/session/niri.*.sock'),None))
                        second = {**inner_env,'XDG_RUNTIME_DIR':str(ipc2.parent),'WAYLAND_DISPLAY':ipc2.name.split('.')[1],
                                  'NIRI_SOCKET':str(ipc2),'DBUS_SESSION_BUS_ADDRESS':'unix:path='+str(ipc2.parent/'bus')}
                        def inner_layers():
                            probe = subprocess.run(['niri','msg','-j','layers'],env=second,capture_output=True,text=True,timeout=2)
                            return probe.returncode == 0 and any(s['namespace']=='adws-taskbar-preview' for s in json.loads(probe.stdout))
                        wait_for(inner,inner_layers)
                        inner_processes = session_processes(ipc2.parent)
                        assert len(inner_processes) >= 3
                        # Closing the actual second Niri window via its parent
                        # does not depend on a quit reply from a dying IPC socket.
                        wins = subprocess.check_output(['niri','msg','-j','windows'],env=client,text=True)
                        own_window = next(w for w in json.loads(wins) if w['pid'] == int(ipc2.name.split('.')[-2]))
                        subprocess.run(['niri','msg','action','close-window','--id',str(own_window['id'])],env=client,check=True,capture_output=True)
                        assert inner.wait(timeout=8) == 0 and not ipc2.parent.parent.exists()
                        check_closed(inner_processes)
                        assert layers() and launcher.poll() is None
                    finally:
                        if inner.poll() is None:
                            inner.terminate(); inner.wait(timeout=8)
                    launcher.send_signal(signal.SIGINT)
                    assert launcher.wait(timeout=8) == 130
                    assert not runtime.parent.exists() and xvfb.poll() is None
                    check_closed(owners)
                except BaseException:
                    log.seek(0);print(log.read());raise
                finally:
                    if launcher.poll() is None:
                        launcher.terminate(); launcher.wait(timeout=8)
        finally:
            xvfb.terminate();xvfb.wait(timeout=5)


if __name__=='__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--binary',type=Path,required=True);parser.add_argument('--screenshot',type=Path)
    args=parser.parse_args();run(args.binary.resolve(strict=True), args.screenshot)
    print('Nested preview mapped on private Niri output; SIGINT cleaned its bar, compositor, bus and temporary directory.')

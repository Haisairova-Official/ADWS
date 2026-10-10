"""Independent plugin-supervisor watchdog; never runs on the GTK thread."""
import json
import ctypes
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from adws_i18n import tr
from adws_plugin_preview import filename, process_start


def folder():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    base = Path(runtime) if runtime else Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))
    return base/'adws/plugin-health'


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def store(record):
    target = folder()/filename(record['instance'])
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged = target.with_suffix('.'+str(os.getpid())+'.tmp')
    try:
        with os.fdopen(os.open(staged, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600), 'w') as stream:
            json.dump(record, stream, ensure_ascii=False)
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)


def health(instance):
    try:
        path = folder()/filename(instance)
        if path.is_symlink() or path.stat().st_size > 16384: return None
        record = json.loads(path.read_text())
        if record.get('instance') != instance or record.get('boot') != boot_id(): return None
        return record if record.get('state') in ('starting','running','failed','stopped','completed') else None
    except (OSError, ValueError, AttributeError): return None


def pulse(child_pid):
    """Called by the worker's actual event loop, not a separate healthy thread."""
    path = os.environ.get('ADWS_PLUGIN_WATCHDOG_BEAT')
    if not path: return
    try:
        data = {'pid':child_pid, 'start':process_start(child_pid)}
        staged = Path(path+'.tmp')
        staged.write_text(json.dumps(data))
        staged.replace(path)
    except (OSError, ValueError): pass


def notify(name, reason):
    try:
        subprocess.run(['notify-send', '--app-name=ADWS', '--urgency=normal', '-t', '8000',
                        tr('插件异常'), tr('插件 %s 已停止运行，详情请查看组件与插件设置。') % name],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.TimeoutExpired): pass


def kill_child(beat):
    try:
        data = json.loads(beat.read_text())
        pid = data['pid']
        if type(pid) is int and pid > 1 and process_start(pid) == data['start']:
            os.killpg(pid, signal.SIGKILL)
    except (OSError, ValueError, KeyError, TypeError): pass


def monitor(command, instance, name, grace=15., limit=10.):
    record = {'instance':instance, 'name':name, 'pid':os.getpid(), 'boot':boot_id(),
              'state':'starting', 'reason':'', 'at':time.time()}
    directory = folder(); directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    beat = directory/('.'+uuid.uuid4().hex+'.beat')
    old = health(instance) or {}
    last_alert = old.get('notified_at', 0)
    record['notified_at'] = last_alert if type(last_alert) in (int,float) and math.isfinite(last_alert) else 0
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    previous = {s:signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    process = None
    try:
        store(record)
        process = subprocess.Popen(command, env={**os.environ,'ADWS_PLUGIN_WATCHDOG_WORKER':'1',
                                  'ADWS_PLUGIN_WATCHDOG_BEAT':str(beat)}, start_new_session=True)
        record['runner_pid'] = process.pid
        store(record)
        deadline = time.monotonic()+grace
        stamp = None
        while not stopped:
            code = process.poll()
            if code is not None:
                record.update(state='completed' if code == 0 else 'failed', reason='' if code == 0 else tr('运行器异常退出（状态 %s）') % code)
                break
            try:
                current = beat.stat().st_mtime_ns
                if stamp != current:
                    stamp = current; deadline = time.monotonic()+limit
                    if record['state'] != 'running': record['state']='running'; store(record)
            except FileNotFoundError: pass
            if time.monotonic() >= deadline:
                record.update(state='failed', reason=tr('插件解释器未响应'))
                break
            time.sleep(.2)
        if stopped: record.update(state='stopped', reason='')
        record['at'] = time.time()
        alert = record['state'] == 'failed' and record['at']-record['notified_at'] >= 60
        if alert: record['notified_at'] = record['at']
        store(record)
        if record['state'] == 'failed':
            print('[plugin:'+instance+'] '+record['reason'], file=sys.stderr, flush=True)
            if alert: notify(name, record['reason'])
            return 1
        return 0
    except OSError as error:
        record.update(state='failed', reason=str(error)[:1024], at=time.time())
        try: store(record)
        except OSError: pass
        notify(name, record['reason'])
        return 1
    finally:
        if process is not None:
            if process.poll() is None:
                process.send_signal(signal.SIGCONT)
                process.terminate()
                try: process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    kill_child(beat)
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            else: kill_child(beat)
            process.wait()
        beat.unlink(missing_ok=True)
        Path(str(beat)+'.tmp').unlink(missing_ok=True)
        for signum, handler in previous.items(): signal.signal(signum, handler)


def reap_orphans():
    # This dedicated watchdog is a Linux subreaper: a killed supervisor cannot
    # leave plugin/helper zombies under an unrelated desktop process.
    deadline = time.monotonic()+1
    while time.monotonic() < deadline:
        try:
            while os.waitpid(-1, os.WNOHANG)[0]: pass
        except ChildProcessError: return
        children = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text().split()
        for child in children:
            try: os.kill(int(child), signal.SIGKILL)
            except ProcessLookupError: pass
        time.sleep(.01)


def run(root, manifest, overrides, timeout):
    spec = {'root':str(root), 'manifest':manifest, 'overrides':overrides, 'timeout':timeout}
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0 or libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot initialize plugin watchdog subreaper')
    try:
        return monitor([sys.executable, str(Path(__file__).with_name('adws_plugin_runner.py')),
                        '--worker-spec-json', json.dumps(spec,ensure_ascii=False)],
                       os.environ.get('ADWS_PLUGIN_INSTANCE') or manifest['id'], manifest.get('name',manifest['id']))
    finally:
        reap_orphans()
        libc.prctl(36, previous.value, 0, 0, 0)

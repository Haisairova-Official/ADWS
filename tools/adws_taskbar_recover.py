"""Bounded recovery requested by the taskbar's independent heartbeat thread."""
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import sys
import time

from adws_runtime import matches, pids, start_taskbar
from adws_health import state_home


def recent_attempts(records, now):
    if not isinstance(records, list) or any(type(v) not in (int, float) for v in records):
        raise ValueError('Invalid recovery history; refusing automatic restart')
    return [v for v in records if now - 600 <= v <= now + 600]


def configuration(argv):
    if not matches('taskbar', argv):
        raise ValueError('Not an ADWS taskbar')
    def option(short, long):
        for i, value in enumerate(argv):
            if value in (short, long) and i + 1 < len(argv):
                return Path(argv[i + 1])
            if value.startswith(long + '='):
                return Path(value.split('=', 1)[1])
        raise ValueError('Missing taskbar configuration')
    return option('-c', '--config'), option('-s', '--style')


def recover(pid):
    # A helper may recover only its still-living direct parent, never a stale PID.
    if pid != os.getppid():
        raise ValueError('Recovery parent changed')
    proc = Path('/proc') / str(pid)
    if proc.stat().st_uid != os.getuid():
        raise ValueError('Different process owner')
    argv = proc.joinpath('cmdline').read_bytes().decode().rstrip('\0').split('\0')
    config, style = configuration(argv)
    fd = os.pidfd_open(pid)
    try:
        if pid != os.getppid():
            return
        directory = state_home() / 'adws'
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'taskbar-recovery.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            history = directory / 'taskbar-recovery.json'
            now = time.time()
            records = recent_attempts(json.loads(history.read_text()) if history.exists() else [], now)
            report = {'time': now, 'pid': pid, 'reason': 'main loop heartbeat missing for 10 seconds',
                      'action': 'restart' if len(records) < 2 else 'rate limited (2 attempts / 10 minutes)'}
            for name in ('status', 'wchan', 'stat'):
                try:
                    report[name] = proc.joinpath(name).read_text()[:8192]
                except OSError:
                    pass
            log = directory / 'taskbar-recovery.log'
            if log.exists() and log.stat().st_size > 512 * 1024:
                log.replace(log.with_suffix('.log.1'))
            with log.open('a') as output:
                output.write(json.dumps(report) + '\n')
            if len(records) >= 2:
                return
            # Record before stopping anything. Malformed/unwritable history fails closed.
            temporary = history.with_suffix('.tmp')
            temporary.write_text(json.dumps(records + [now]))
            temporary.replace(history)
            poller = select.poll()
            poller.register(fd, select.POLLIN)
            if poller.poll(0):
                return
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            if not poller.poll(2000):
                signal.pidfd_send_signal(fd, signal.SIGKILL)
                if not poller.poll(2000):
                    raise RuntimeError('Taskbar did not exit; not starting a duplicate')
            if pids('taskbar'):
                return
            ok, message = start_taskbar(config, style)
            with log.open('a') as output:
                output.write(json.dumps({'time': time.time(), 'restarted': ok, 'message': message}) + '\n')
    finally:
        os.close(fd)


if __name__ == '__main__':
    os.setsid()
    try:
        recover(int(sys.argv[1]))
    except (OSError, ValueError, RuntimeError) as error:
        print('ADWS taskbar recovery:', error, file=sys.stderr)
        sys.exit(1)

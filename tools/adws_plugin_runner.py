"""Bounded JSON-lines plugin runner used by CLI and taskbar renderers."""
import argparse
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from adws_plugin_api import finite, settings
from adws_i18n import tr

LIMIT = 1024 * 1024


def write_line(text, stream):
    try:
        print(text, file=stream, flush=True)
    except BrokenPipeError:
        # Also prevent Python's final buffered flush from reporting the same
        # closed consumer again during interpreter shutdown.
        try:
            with open(os.devnull, 'wb') as sink:
                os.dup2(sink.fileno(), stream.fileno())
        except (OSError, ValueError):
            pass
        raise


def report_failure(error, plugin_id=None):
    try:
        prefix = f'[plugin:{plugin_id}] ' if plugin_id else ''
        write_line(prefix + str(error), sys.stderr)
        text = tr('插件运行失败')
        write_line(json.dumps({'text': text, 'primary': text, 'secondary': '',
                               'tooltip': text, 'class': 'error'}, ensure_ascii=False), sys.stdout)
    except BrokenPipeError:
        return 0  # The consumer has gone; there is nowhere to display an error.
    return 1


def execute(root, manifest, overrides, timeout=30):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout must be finite and positive')
    values = settings(manifest, overrides)
    command = [sys.executable, str(root / manifest['entry'])]
    if 'renderer' not in manifest:
        command.append('--output-json')
    if 'renderer' in manifest or manifest.get('settingsSchema'):
        command += ['--settings-json', json.dumps(values, ensure_ascii=False)]
    process = None
    def stop(_signum, _frame): raise InterruptedError('Plugin stopped')
    previous = signal.signal(signal.SIGTERM, stop)
    count = 0
    try:
        process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            buffers = {'stdout': b'', 'stderr': b''}
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            deadline = time.monotonic() + timeout
            while selector.get_map():
                if time.monotonic() >= deadline: raise TimeoutError('Plugin output timed out')
                for key, _ in selector.select(min(.2, max(0, deadline-time.monotonic()))):
                    data = os.read(key.fileobj.fileno(), 65536)
                    kind = key.data
                    if not data:
                        selector.unregister(key.fileobj)
                        if buffers[kind]: data = b'\n'
                        else: continue
                    buffers[kind] += data
                    if len(buffers[kind]) > LIMIT: raise ValueError('Plugin output exceeds 1 MiB')
                    while b'\n' in buffers[kind]:
                        line, buffers[kind] = buffers[kind].split(b'\n', 1)
                        if kind == 'stderr':
                            write_line(f'[plugin:{manifest["id"]}] {line.decode("utf-8", errors="replace")}', sys.stderr)
                            continue
                        payload = json.loads(line)
                        if not isinstance(payload, dict): raise ValueError('Plugin output must be a JSON object')
                        rows = 'panel.rows-v1' in manifest.get('interfaces', []) or manifest.get('renderer') == 'panel.rows-v1'
                        required = 'primary' if rows else 'text'
                        if not isinstance(payload.get(required), str): raise ValueError('Missing text field: ' + required)
                        for field in ('text', 'primary', 'secondary', 'tooltip', 'alt'):
                            if field in payload and not isinstance(payload[field], str): raise ValueError('Invalid text field: ' + field)
                        classes = payload.get('class', '')
                        if not isinstance(classes, str) and not (isinstance(classes, list) and all(isinstance(c, str) for c in classes)):
                            raise ValueError('Invalid CSS class')
                        if 'percentage' in payload and (not finite(payload['percentage']) or not 0 <= payload['percentage'] <= 100):
                            raise ValueError('Invalid percentage')
                        write_line(json.dumps(payload, ensure_ascii=False), sys.stdout)
                        count += 1
                        # Legacy streams emit only changed data and have no heartbeat contract.
                        deadline = time.monotonic() + timeout if 'renderer' in manifest else float('inf')
            # Once both pipes close there can be no further updates. Legacy
            # streams may stay quiet with open pipes, but must now exit promptly.
            code = process.wait(timeout=min(timeout, max(.1, deadline-time.monotonic())))
            if code or not count: raise ValueError(f'Plugin exited with status {code}; records={count}')
        return 0
    except BrokenPipeError:
        return 0
    except (OSError, ValueError, RecursionError, OverflowError, subprocess.TimeoutExpired) as error:
        return report_failure(error, manifest['id'])
    finally:
        if process is not None:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait()
            process.stdout.close()
            process.stderr.close()
        signal.signal(signal.SIGTERM, previous)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package')
    parser.add_argument('--settings-json', default='{}')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    from adws_plugin import load_manifest, materialize
    path = Path(args.package)
    try:
        return execute(materialize(path), load_manifest(path), json.loads(args.settings_json), args.timeout)
    except BrokenPipeError:
        return 0
    except (OSError, ValueError) as error:
        return report_failure(error)


if __name__ == '__main__':
    raise SystemExit(main())

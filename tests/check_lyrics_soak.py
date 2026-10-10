#!/usr/bin/env python3
"""Compare real NCM render payloads through Rust/Python and the GTK rows renderer.

python3 tests/check_lyrics_soak.py --seconds 90
Use --sanitize for C address/undefined-behaviour checks (GTK leak caches excluded).
Synthetic playback has a 35-second pause with the original 15-second heartbeat.
This does not emulate browser IPC/network or the real Wayland compositor.
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=90)
    parser.add_argument('--backend', choices=('both', 'rust', 'python'), default='both')
    parser.add_argument('--sanitize', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        sys.path.insert(0, str(ROOT / 'tools'))
        import adws_plugin_runner
        return adws_plugin_runner.dispatch(ROOT / 'tests', {
            'id':'org.Example.NCMSoak', 'entry':'soak_ncm_fixture.py', 'renderer':'panel.rows-v1'
        }, {}, 30)
    if args.seconds < 15:
        parser.error('Use at least 15 seconds; use 90 to include pause and resume.')
    with tempfile.TemporaryDirectory(prefix='adws-lyrics-soak-') as directory:
        binary = Path(directory) / 'soak'
        flags = subprocess.check_output(['pkg-config', '--cflags', '--libs',
            'gtk+-3.0', 'json-glib-1.0', 'gtk-layer-shell-0'], text=True)
        compiler = ['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror']
        if args.sanitize:
            compiler += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        subprocess.run([*compiler, '-o', str(binary), str(ROOT/'src/panel-rows/test-runner-soak.c'),
                        *shlex.split(flags)], check=True)
        for backend in (('rust', 'python') if args.backend == 'both' else (args.backend,)):
            env = {**os.environ, 'GDK_BACKEND':'x11', 'ADWS_PLUGIN_RUNNER':backend}
            if args.sanitize:
                env.update(ASAN_OPTIONS='detect_leaks=0:halt_on_error=1:quarantine_size_mb=16',
                           UBSAN_OPTIONS='halt_on_error=1')
            print(f'Backend: {backend}', flush=True)
            subprocess.run(['xvfb-run', '-a', str(binary), str(args.seconds),
                shlex.join([sys.executable, str(Path(__file__).resolve()), '--worker'])],
                env=env, check=True, timeout=args.seconds+30)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

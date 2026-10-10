"""ADWS clipboard picker over cliphist; no terminal or external menu frontend."""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import selectors
import subprocess
import sys
import time
from adws_i18n import tr
import adws_clipboard_pins as pins

def run(args,**kwargs):return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8,**kwargs).stdout

def entries():
    # cliphist caps its own history; cap the displayed list too.
    text=run(['cliphist','list']).decode(errors='replace')
    return [line for line in text.splitlines() if '\t' in line][:500]

def copy_entry(line):
    data=pins.read(line) if pins.identity(line) else run(['cliphist','decode'],input=(line+'\n').encode())
    run(['wl-copy'],input=data)

def list_records():
    fixed=pins.records();sources={item['source'] for item in fixed}
    return [item['line'] for item in fixed]+[line for line in entries() if line not in sources]

def toggle_pin(line):
    if pins.identity(line):
        # Unpin returns the item to ordinary history, even after that history expired.
        run(['cliphist','store'],input=pins.read(line));pins.remove(line)
    else:
        try:data=preview_data(line,limit=pins.MAX_BYTES,timeout=5)
        except ValueError as exc:
            if str(exc)=='Preview too large':raise ValueError(tr('单条固定内容不能超过 32 MiB。')) from exc
            raise
        pins.store(line,data)
    return list_records()

def delete_entry(line):
    if pins.identity(line):
        original=next((item['source'] for item in pins.records() if item['line']==line),None)
        if original and original in entries():run(['cliphist','delete'],input=(original+'\n').encode())
        pins.remove(line)
    else:run(['cliphist','delete'],input=(line+'\n').encode())

def preview_data(line, *, limit=8*1024*1024, timeout=2, cancelled=None):
    """Decode a preview with bounded memory/time; never change the clipboard."""
    if cancelled and cancelled.is_set(): return b''
    if pins.identity(line):return pins.read(line,limit=limit)
    value=(line+'\n').encode()
    if len(value)>4096: raise ValueError('Preview identifier too large')
    if cancelled and cancelled.is_set(): return b''
    with subprocess.Popen(['cliphist','decode'],stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as process:
        try:
            process.stdin.write(value);process.stdin.close()
            deadline=time.monotonic()+timeout;data=bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout,selectors.EVENT_READ)
                while True:
                    if cancelled and cancelled.is_set(): return b''
                    remaining=deadline-time.monotonic()
                    if remaining<=0: raise TimeoutError('Preview timed out')
                    if not selector.select(min(.05,remaining)): continue
                    chunk=os.read(process.stdout.fileno(),min(65536,limit-len(data)+1))
                    if not chunk: break
                    data.extend(chunk)
                    if len(data)>limit: raise ValueError('Preview too large')
            while process.poll() is None:
                if cancelled and cancelled.is_set():return b''
                if time.monotonic()>=deadline:raise TimeoutError('Preview timed out')
                time.sleep(.01)
            if process.returncode:
                raise ValueError('Preview unavailable')
            return bytes(data)
        finally:
            if process.poll() is None: process.kill()
            process.wait()

def watcher_exists():
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():continue
        try:
            if path.stat().st_uid!=os.getuid():continue
            argv=path.joinpath('cmdline').read_bytes().decode().rstrip('\0').split('\0')
            if argv and Path(argv[0]).name=='wl-paste' and '--watch' in argv and any(Path(a).name=='cliphist' for a in argv[1:]):return True
        except (OSError,UnicodeError):pass
    return False

def ensure_watcher():
    if not all(shutil.which(name) for name in ('cliphist','wl-paste','wl-copy')):raise RuntimeError(tr('剪贴板历史需要 cliphist 和 wl-clipboard。'))
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR') or '/tmp')/('adws-clipboard-'+str(os.getuid())+'.lock')
    with runtime.open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not watcher_exists():
            subprocess.Popen(['wl-paste','--watch','cliphist','store'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)

def picker():
    from adws_clipboard_gui import picker as show_picker
    return show_picker()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--watch-start',action='store_true');args=parser.parse_args()
    try:
        if args.watch_start:
            ensure_watcher();print('ready');return 0
        return picker()
    except Exception as error:
        print(str(error),file=sys.stderr)
        if shutil.which('notify-send'):subprocess.run(['notify-send','ADWS',str(error)],check=False,timeout=5)
        return 1
if __name__=='__main__':raise SystemExit(main())

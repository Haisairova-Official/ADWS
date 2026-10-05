"""Bounded spectrum stream for Waybar, owning exactly one CAVA child."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

CHARS='▁▂▃▄▅▆▇█'
def frame(line,bars=10):
    try:values=[int(v) for v in line.strip().split(';') if v.strip()]
    except ValueError:return None
    if len(values)!=bars:return None
    return ''.join(CHARS[max(0,min(len(CHARS)-1,v))] for v in values)

def stream():
    bars=10;print(CHARS[0]*bars,flush=True)
    if not shutil.which('cava'):return 0
    config='''[general]
bars = 10
framerate = 15
sleep_timer = 5
[input]
source = auto
[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 7
bar_delimiter = 59
frame_delimiter = 10
'''
    child=None
    def stop(*_):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        with tempfile.TemporaryDirectory(prefix='adws-cava-') as directory:
            path=Path(directory)/'config';path.write_text(config)
            child=subprocess.Popen(['cava','-p',str(path)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
            previous=None
            for line in child.stdout:
                current=frame(line)
                if current and current!=previous:print(current,flush=True);previous=current
    except BrokenPipeError:return 0
    finally:
        if child:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            child.stdout.close()
    return 0
if __name__=='__main__':raise SystemExit(stream())

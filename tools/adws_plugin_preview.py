"""Read-only panel snapshots shared with the layout preview, without a second plugin."""
import json
import os
from itertools import islice
from pathlib import Path


def filename(instance):
    key = 14695981039346656037
    for byte in instance.encode('utf-8'):
        key = ((key ^ byte) * 1099511628211) & ((1 << 64)-1)
    return f'{key:016x}.json'


def process_start(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]


def publish(payload, instance):
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime or not Path(runtime).is_dir(): return
    minimal = {key: str(payload[key])[:4096] for key in ('primary','secondary','text','class') if key in payload}
    if not minimal: return
    record = {'instance':instance,'pid':os.getpid(),'start':process_start(os.getpid()), **minimal}
    folder = Path(runtime)/'adws/plugin-preview'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    path = folder/filename(instance)
    staged = path.with_suffix(f'.{os.getpid()}.tmp')
    try:
        fd=os.open(staged,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(record,stream,ensure_ascii=False)
        os.replace(staged,path)
    finally:
        try:staged.unlink()
        except FileNotFoundError:pass


def read():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime: return {}
    snapshots = {}
    for path in islice((Path(runtime)/'adws/plugin-preview').glob('*.json'),128):
        try:
            if path.is_symlink() or path.stat().st_size>131072: continue
            data=json.loads(path.read_text())
            if not isinstance(data,dict) or not isinstance(data.get('instance'),str): continue
            if not isinstance(data.get('pid'),int) or isinstance(data['pid'],bool) or data['pid']<=0: continue
            if process_start(data['pid']) != data['start']: continue
            if not all(isinstance(data[k],str) for k in ('primary','secondary','text','class') if k in data):continue
            snapshots[data['instance']] = data
        except (OSError,ValueError,KeyError,TypeError): continue
    return snapshots

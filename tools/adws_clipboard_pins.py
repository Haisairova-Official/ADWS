"""Persistent clipboard pins, committed atomically as private directories."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from adws_i18n import tr

MAX_BYTES=32*1024*1024
PREFIX='adws-pin:'


def root():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'adws/clipboard-pins'


def identity(line):
    value=line.split('\t',1)[0]
    return value[len(PREFIX):] if re.fullmatch(r'adws-pin:[0-9a-f]{64}',value) else None


def records():
    folder=root()
    if not folder.exists():return []
    result=[]
    for entry in folder.iterdir():
        if not re.fullmatch('[0-9a-f]{64}',entry.name) or not entry.is_dir():continue
        try:
            meta=entry/'meta.json'
            if meta.stat().st_size>32768:continue
            value=json.loads(meta.read_text())
            source=value.get('source');created=value.get('created')
            if not isinstance(source,str) or '\t' not in source or len(source)>4096 or not isinstance(created,int):continue
            if not (entry/'content').is_file():continue
            result.append({'line':PREFIX+entry.name+'\t'+source.split('\t',1)[1],'source':source,'created':created})
        except (OSError,ValueError,AttributeError):continue
    return sorted(result,key=lambda item:item['created'],reverse=True)


def store(source,data):
    if len(data)>MAX_BYTES:raise ValueError(tr('单条固定内容不能超过 32 MiB。'))
    if '\t' not in source or len(source)>4096:raise ValueError(tr('无法固定这条记录。'))
    folder=root();folder.mkdir(parents=True,exist_ok=True,mode=0o700);folder.chmod(0o700)
    key=hashlib.sha256(data).hexdigest();target=folder/key
    if target.is_dir():return PREFIX+key+'\t'+source.split('\t',1)[1]
    if len(records())>=100:raise ValueError(tr('最多固定 100 条记录，请先取消部分固定。'))
    pending=Path(tempfile.mkdtemp(prefix='.pending-',dir=folder))
    try:
        for name,content in (('content',data),('meta.json',json.dumps({'source':source,'created':time.time_ns()},ensure_ascii=False).encode())):
            file=pending/name
            with file.open('wb') as output:output.write(content);output.flush();os.fsync(output.fileno())
            file.chmod(0o600)
        try:pending.rename(target)
        except FileExistsError:
            if not target.is_dir():raise
    finally:
        if pending.exists():shutil.rmtree(pending)
    return PREFIX+key+'\t'+source.split('\t',1)[1]


def read(line,limit=MAX_BYTES):
    key=identity(line)
    if key is None:raise ValueError(tr('无效的固定记录。'))
    with (root()/key/'content').open('rb') as file:data=file.read(limit+1)
    if len(data)>limit:raise ValueError(tr('内容过大，无法预览。'))
    return data


def remove(line):
    key=identity(line)
    if key is None:raise ValueError(tr('无效的固定记录。'))
    folder=root()/key
    if folder.is_dir():shutil.rmtree(folder)

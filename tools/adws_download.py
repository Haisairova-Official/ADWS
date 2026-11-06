"""Bounded, verified transfers with persistent HTTP range resume."""
from __future__ import annotations
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_DOWNLOAD = 512 * 1024 * 1024
CHUNK = 64 * 1024


def _url(url, allow_local_http=False):
    parts = urllib.parse.urlsplit(url)
    local = allow_local_http and parts.scheme == 'http' and parts.hostname in ('127.0.0.1','localhost','::1')
    if (parts.scheme != 'https' and not local) or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Downloads require HTTPS without credentials or fragments')


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(CHUNK): digest.update(data)
    return digest.hexdigest()


def _metadata(path, value):
    temporary = path.with_name(path.name + '.new')
    if temporary.is_symlink(): raise ValueError('Download metadata cannot be a symlink')
    with temporary.open('w') as stream:
        json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def fetch(url, target, sha256, *, progress=None, retries=3, max_bytes=MAX_DOWNLOAD,
          timeout=30, allow_local_http=False, retry_delay=.5):
    """Return a verified file; incomplete bytes remain resumable between processes.

    Resume is allowed only for the exact requested URL, expected digest and strong
    ETag. Every 206 must match offset, total size and entity tag. An ignored Range
    restarts from byte zero. Existing verified downloads are reused without HTTP.
    """
    _url(url,allow_local_http)
    if not isinstance(sha256,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',sha256):
        raise ValueError('An expected SHA-256 from the publisher/user is required')
    if not 1 <= retries <= 8 or max_bytes < 1: raise ValueError('Invalid transfer limits')
    sha256=sha256.lower();target=Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_name(target.name+'.part');metadata=target.with_name(target.name+'.part.json');lock=target.with_name(target.name+'.lock')
    for path in (target,partial,metadata,lock):
        if path.is_symlink():raise ValueError('Download paths cannot be symlinks')
    with lock.open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if target.is_file() and target.stat().st_size<=max_bytes and _digest(target)==sha256:
            if progress:progress(target.stat().st_size,target.stat().st_size)
            return target
        # A prior process may have completed the transfer before it could rename.
        try: saved=json.loads(metadata.read_text())
        except (OSError,ValueError): saved={}
        if (isinstance(saved,dict) and saved.get('url')==url and saved.get('sha256')==sha256
            and partial.is_file() and partial.stat().st_size<=max_bytes and _digest(partial)==sha256):
            os.replace(partial,target);metadata.unlink(missing_ok=True)
            if progress:progress(target.stat().st_size,target.stat().st_size)
            return target
        errors=[]
        for attempt in range(retries):
            state={}
            try:
                try:state=json.loads(metadata.read_text())
                except (OSError,ValueError):pass
                if not isinstance(state,dict):state={}
                offset=partial.stat().st_size if partial.is_file() else 0
                etag=state.get('etag','')
                resumable=(state.get('url')==url and state.get('sha256')==sha256 and isinstance(etag,str)
                           and re.fullmatch(r'"[^"\r\n]+"',etag) and isinstance(state.get('total'),int)
                           and 0<offset<state['total']<=max_bytes)
                if not resumable:offset=0
                headers={'User-Agent':'ADWS-verified-download','Accept-Encoding':'identity'}
                if offset:headers.update(Range=f'bytes={offset}-',**{'If-Range':etag})
                request=urllib.request.Request(url,headers=headers)
                with urllib.request.urlopen(request,timeout=timeout) as response:
                    _url(response.geturl(),allow_local_http)
                    status=response.status
                    incoming_etag=response.headers.get('ETag','')
                    if response.headers.get('Content-Encoding','identity') not in ('identity',''):
                        raise ValueError('Encoded transfer cannot be safely resumed')
                    length=response.headers.get('Content-Length')
                    length=int(length) if length is not None else None
                    if status==206:
                        span=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                        if (not offset or not span or int(span[1])!=offset or int(span[2])<offset
                            or int(span[3])!=state['total'] or int(span[2])>=int(span[3])
                            or incoming_etag!=etag or (length is not None and length!=int(span[2])-offset+1)):
                            partial.unlink(missing_ok=True);metadata.unlink(missing_ok=True)
                            raise ValueError('Invalid resume range or changed entity tag')
                        total=int(span[3]);expected_end=int(span[2])+1
                    elif status==200:
                        offset=0;total=length;expected_end=length
                    else:raise ValueError('Unexpected HTTP status '+str(status))
                    if total is not None and not 0<=total<=max_bytes:raise ValueError('Download exceeds size limit')
                    _metadata(metadata,{'url':url,'sha256':sha256,'etag':incoming_etag,'total':total})
                    count=offset;last=0.0
                    if progress:progress(count,total)
                    with partial.open('ab' if offset else 'wb') as stream:
                        while data:=response.read(CHUNK):
                            count+=len(data)
                            if count>max_bytes or (total is not None and count>total):raise ValueError('Download exceeds declared size')
                            stream.write(data)
                            now=time.monotonic()
                            if progress and now-last>=.1:progress(count,total);last=now
                        stream.flush();os.fsync(stream.fileno())
                    if expected_end is not None and count!=expected_end:raise OSError('Download interrupted before declared end')
                    if total is not None and count!=total:raise OSError('Partial response requires another request')
                if _digest(partial)!=sha256:
                    partial.unlink(missing_ok=True);metadata.unlink(missing_ok=True)
                    raise ValueError('Downloaded file failed SHA-256 verification')
                os.replace(partial,target);metadata.unlink(missing_ok=True)
                if progress:progress(target.stat().st_size,target.stat().st_size)
                return target
            except (OSError,ValueError,http.client.HTTPException) as error:
                if isinstance(error,urllib.error.HTTPError) and error.code==416:
                    partial.unlink(missing_ok=True);metadata.unlink(missing_ok=True)
                errors.append(str(error))
                if attempt+1<retries:time.sleep(retry_delay*(attempt+1))
        raise RuntimeError('Download failed; verified destination unchanged: '+'; '.join(errors))

"""Download a reviewed, verified ADWS release and enter its installation planner."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import stat
import urllib.parse
import urllib.request

from adws_download import fetch, _digest
from adws_i18n import chinese
from adws_update import REPOSITORY, RELEASES_API, read_json, version_key
from adws_upgrade import extract, package


def environment():
    try: distro=platform.freedesktop_os_release().get('ID','unknown')
    except OSError: distro='unknown'
    return {'system':platform.system(),'distro':distro,'architecture':platform.machine(),
            'arch_prebuilt':distro=='arch' and platform.machine()=='x86_64'}


def transfer_url(url, mirror=None):
    existing=os.environ.get('ADWS_GITHUB_PROXY','').strip()
    if mirror and not chinese():raise ValueError('Download mirrors are offered only in a Chinese locale')
    if mirror and existing and mirror.rstrip('/')!=existing.rstrip('/'):
        raise ValueError('An existing ADWS GitHub mirror is configured; do not layer another mirror')
    if mirror and any(os.environ.get(name) for name in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')) and not existing:
        raise ValueError('A network proxy is already configured; keep it instead of adding a mirror')
    selected=existing or mirror
    if not selected:return url
    parts=urllib.parse.urlsplit(selected)
    if parts.scheme!='https' or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Mirror must be an HTTPS base URL without credentials or query')
    # Do not send arbitrary user-supplied hosts through a GitHub-only mirror.
    if urllib.parse.urlsplit(url).hostname not in ('github.com','api.github.com'):
        raise ValueError('Configured GitHub mirror cannot proxy this download host')
    return selected.rstrip('/')+'/'+url


def companion_digest(url, asset_name, mirror=None):
    request=urllib.request.Request(transfer_url(url,mirror),headers={'User-Agent':'ADWS-bootstrap'})
    with urllib.request.urlopen(request,timeout=15) as response:
        data=response.read(8193)
    if len(data)>8192:raise ValueError('Checksum file exceeds size limit')
    for line in data.decode('utf-8').splitlines():
        match=re.fullmatch(r'([0-9a-fA-F]{64})(?:\s+\*?(.+))?',line.strip())
        if match and (match[2] is None or match[2]==asset_name):return match[1].lower()
    raise ValueError('Published checksum did not identify the chosen archive')


def release_plan(release='latest', *, source=False, sha256=None, mirror=None):
    if release!='latest':version_key(release)
    url=RELEASES_API+'/latest' if release=='latest' else RELEASES_API+'/tags/'+urllib.parse.quote(release,safe='')
    data=read_json(transfer_url(url,mirror),timeout=15)
    if not isinstance(data,dict) or data.get('draft'):raise ValueError('Release metadata is invalid or draft')
    tag=data.get('tag_name')
    if not isinstance(tag,str):raise ValueError('Release metadata has no version tag')
    version_key(tag)
    assets=data.get('assets') or []
    if not isinstance(assets,list):raise ValueError('Invalid release asset list')
    if source:
        asset=next((a for a in assets if isinstance(a,dict) and re.fullmatch(r'ADWS[\w.-]+_(?:source|src)\.zip',str(a.get('name','')),re.I)),None)
        name=asset['name'] if asset else None
        download=(f'https://github.com/{REPOSITORY}/releases/download/'+urllib.parse.quote(tag,safe='')+'/'+urllib.parse.quote(name,safe='')) if name else f'https://github.com/{REPOSITORY}/archive/refs/tags/'+urllib.parse.quote(tag,safe='')+'.zip'
        digest=(asset or {}).get('digest','')
        digest=digest[7:] if isinstance(digest,str) and re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest) else None
        prebuilt=False
    else:
        download,digest,prebuilt=package(data)
        if not prebuilt:raise ValueError('No compatible Arch prebuilt asset; review source build explicitly with --source')
        name=urllib.parse.unquote(download.rsplit('/',1)[1])
    expected=sha256 or digest
    if not expected and name and any(isinstance(a,dict) and a.get('name')==name+'.sha256' for a in assets):
        expected=companion_digest(download+'.sha256',name,mirror)
    if not expected:raise ValueError('This archive has no published checksum; supply a trusted --sha256 (source build remains explicit)')
    return artifact_plan(download,expected,source=source,mirror=mirror,tag=tag,prebuilt=prebuilt)


def artifact_plan(url, sha256, *, source=False, mirror=None, tag=None, prebuilt=None):
    from adws_download import _url
    _url(url)
    if not isinstance(sha256,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',sha256):raise ValueError('A trusted SHA-256 is required')
    host=environment()
    if host['system']!='Linux':raise ValueError('ADWS installation currently targets Linux')
    if not host['arch_prebuilt'] and not source:raise ValueError('This platform requires explicit --source selection')
    return {'schema':1,'release':tag,'repository':REPOSITORY,'url':url,'transfer_url':transfer_url(url,mirror),
            'sha256':sha256.lower(),'source':source,'prebuilt':prebuilt,'environment':host,
            'operations':['download/resume with progress','verify publisher SHA-256','validate archive paths and payload','open downloaded installation planner'],
            'notice':'Existing installation directories are preserved. The installer asks once for its reviewed configuration plan.'}


def progress(done,total):
    suffix=f' / {total/1048576:.1f} MiB ({done*100/total:.1f}%)' if total else ' / size not provided'
    print(f'\rDownload {done/1048576:.1f} MiB'+suffix,end='',file=sys.stderr,flush=True)


def default_cache():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/bootstrap'


def validate_payload(root, plan):
    for name in ENTRYPOINTS:
        if not (root/name).is_file() or (root/name).is_symlink():raise ValueError('Release lacks a regular installer entrypoint: '+name)
    if not plan['source']:
        manifest=json.loads((root/'prebuilt/manifest.json').read_text())
        if not isinstance(manifest,dict) or manifest.get('os')!='arch' or manifest.get('arch')!='x86_64':
            raise ValueError('Archive prebuilt platform does not match reviewed plan')
        hashes=manifest.get('sha256')
        if not isinstance(hashes,dict):raise ValueError('Archive has no native component hashes')
        for name in ('libniri_taskbar.so','libadws_panel.so','libwaybar-space.so','adws-plugin-runner','adws-start-menu'):
            if _digest(root/'prebuilt'/name)!=hashes.get(name):raise ValueError('Invalid prebuilt component: '+name)
    if plan.get('release'):
        from adws_upgrade import installed_version
        if installed_version(root)!=version_key(plan['release']):raise ValueError('Archive version differs from selected release')


def archive_inventory(archive_path):
    """Derive original member hashes from the verified ZIP, never a mutable marker."""
    from adws_upgrade import MAX_EXPANDED
    with zipfile.ZipFile(archive_path) as bundle:
        entries=bundle.infolist()
        if len(entries)>30000 or sum(e.file_size for e in entries)>MAX_EXPANDED:raise ValueError('Archive exceeds size limit')
        names=set()
        for entry in entries:
            name=PurePosixPath(entry.filename);mode=entry.external_attr>>16
            if name.is_absolute() or '..' in name.parts or '\\' in entry.filename or entry.filename in names or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR):raise ValueError('Unsafe archive member')
            names.add(entry.filename)
        roots=[str(PurePosixPath(name).parent) for name in names if PurePosixPath(name).name=='build-info.json' and str(PurePosixPath(name).parent/'adws') in names]
        if len(roots)!=1:raise ValueError('Archive does not identify a unique ADWS source tree')
        root=PurePosixPath(roots[0]);result={}
        for entry in entries:
            path=PurePosixPath(entry.filename)
            if entry.is_dir() or not path.is_relative_to(root):continue
            name=str(path.relative_to(root));digest=hashlib.sha256()
            with bundle.open(entry) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
            result[name]=digest.hexdigest()
        return result


def verify_cached_tree(destination, expected):
    for name,digest in expected.items():
        path=destination
        for component in PurePosixPath(name).parts:
            path=path/component
            if path.is_symlink():raise ValueError('Cached source changed to a symlink: '+name)
        if not path.is_file() or _digest(path)!=digest:raise ValueError('Cached source or resource changed: '+name)


def prepare(plan, *, cache=None, destination=None, transfer=fetch, progress_callback=progress):
    """Persist a verified worktree for subsequent installer --resume runs."""
    if plan.get('schema')!=1:raise ValueError('Unsupported bootstrap plan')
    cache=Path(cache) if cache else default_cache()
    cache.mkdir(parents=True,exist_ok=True)
    archive=cache/(plan['sha256']+'.zip')
    transfer(plan['transfer_url'],archive,plan['sha256'],progress=progress_callback)
    if _digest(archive)!=plan['sha256']:
        raise ValueError('Archive changed after verified transfer')
    destination=(Path(destination).expanduser().absolute() if destination else cache/(plan['sha256']+'-source'))
    marker=destination/'.adws-bootstrap.json'
    if destination.is_symlink():raise ValueError('Installation destination cannot be a symlink')
    if destination.exists():
        try:saved=json.loads(marker.read_text())
        except (OSError,ValueError):raise ValueError('Destination already exists and is not this verified bootstrap; no files replaced')
        if not isinstance(saved,dict):raise ValueError('Invalid cached bootstrap marker')
        if saved.get('sha256')!=plan['sha256'] or saved.get('url')!=plan['url']:
            raise ValueError('Destination belongs to another release; choose an empty destination')
        verify_cached_tree(destination,archive_inventory(archive))
        validate_payload(destination,plan)
        return destination
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.adws-bootstrap-',dir=destination.parent) as temporary:
        # Reuse updater's bounded regular-file ZIP extractor, with a fresh empty
        # directory so no pre-existing symlink can redirect an archive member.
        staged=extract(archive,Path(temporary)/'unpacked')
        validate_payload(staged,plan)
        entry_hashes={name:_digest(staged/name) for name in ENTRYPOINTS}
        (staged/'.adws-bootstrap.json').write_text(json.dumps({'url':plan['url'],'sha256':plan['sha256'],'entrypoint_hashes':entry_hashes},indent=2)+'\n')
        if destination.exists():raise ValueError('Destination appeared during download; no files replaced')
        # rename cannot overwrite a populated directory; cache is user-owned.
        os.rename(staged,destination)
    return destination


ENTRYPOINTS=('install.sh','scripts/adws-install.sh','tools/adws_install_workflow.py')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    origin=parser.add_mutually_exclusive_group();origin.add_argument('--release',default='latest');origin.add_argument('--url')
    parser.add_argument('--sha256');parser.add_argument('--source',action='store_true')
    parser.add_argument('--mirror');parser.add_argument('--cache',type=Path);parser.add_argument('--destination',type=Path)
    parser.add_argument('--plan',action='store_true');parser.add_argument('--yes',action='store_true')
    parser.add_argument('install_args',nargs=argparse.REMAINDER,help='Arguments after -- are passed to install.sh, including --mode and --resume')
    args=parser.parse_args(argv)
    if os.geteuid()==0:raise ValueError('Run this entry as the target desktop user; only package installation uses sudo')
    if args.url:plan=artifact_plan(args.url,args.sha256,source=args.source,mirror=args.mirror)
    else:plan=release_plan(args.release,source=args.source,sha256=args.sha256,mirror=args.mirror)
    print(json.dumps(plan,ensure_ascii=False,indent=2))
    if args.plan:return 0
    if not args.yes:
        if not sys.stdin.isatty():raise ValueError('Unattended downloads require --yes after reviewing --plan')
        if input('Download and open this installer? [y/N] ').strip().lower() not in ('y','yes'):return 130
    root=prepare(plan,cache=args.cache,destination=args.destination)
    print('\nVerified installer: '+str(root))
    forwarded=args.install_args[1:] if args.install_args[:1]==['--'] else args.install_args
    if args.source and '--build-fallback' not in forwarded:forwarded=['--build-fallback',*forwarded]
    env={key:value for key,value in os.environ.items() if not key.startswith('ADWS_INSTALL_') and key!='ADWS_NIRI_METHOD'}
    return subprocess.run(['bash',str(root/'install.sh'),*forwarded],cwd=root,env=env).returncode

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print('Bootstrap incomplete: '+str(exc),file=sys.stderr);raise SystemExit(1)
    except (EOFError,KeyboardInterrupt):raise SystemExit(130)

"""Review only known package-created XDG startups; never adopt unknown owners.

Metadata references:
https://manpages.debian.org/trixie/dpkg/dpkg-query.1.en.html
https://ftp.rpm.org/max-rpm/s1-rpm-query-parts.html
Arch's installed mtree SHA256 path is exercised against the real bootstrap.
"""
import configparser
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess


def reviewed_package_owners(features, package_candidates, config_home, niri_path=None, *, audit_options=None,
                            system_autostart_dir='/etc/xdg/autostart'):
    from adws_install_startup import audit
    config=Path(config_home).expanduser().absolute();options=dict(audit_options or {})
    before=audit(config,niri_path=niri_path,**options)
    rows={row['id']:row for row in features['features']};selected=set(package_candidates)
    entries=[]
    if 'input' in rows and (rows['input'].get('provider') or 'fcitx5')=='fcitx5' and 'fcitx5' in selected:
        source=Path(system_autostart_dir)/'org.fcitx.Fcitx5.desktop'
        target=config/'autostart'/source.name
        # Existing system/user entries are personal installation state. This
        # policy is exclusively for an absent entry created by our package step.
        if not (source.exists() or source.is_symlink() or target.exists() or target.is_symlink()):
            owners=['fcitx5','fcitx5-data'] if features['manager']=='apt-get' else ['fcitx5']
            entries.append({'provider':'fcitx5','component':'input-method','source':str(source),
                            'target':str(target),'requested_package':'fcitx5','allowed_package_owners':owners,
                            'action':'mask-new-package-xdg','before_source':None,'before_target':None})
    return {'schema_version':1,'manager':features['manager'],'config_home':str(config),
            'niri_path':before['niri_path'],'audit_options':{key:[str(p) for p in value] if isinstance(value,list) else value for key,value in options.items()},
            'before_audit':before,'entries':entries,'snapshot_targets':[entry['target'] for entry in entries],
            'policy':'Only mask newly installed, package-verified standard XDG entries; Niri starts are separately opt-in. Existing user/system owners are preserved.',
            'conflicts':before['unknown']+before['conflicts']}


def package_file_identity(path, manager, run=None):
    """Require package ownership AND unchanged package-file content metadata."""
    run=run or subprocess.run;path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Expected a regular package-owned desktop file')
    data=path.read_bytes()
    def query(argv):
        result=run(argv,capture_output=True,text=True,timeout=20)
        if result.returncode:raise ValueError('Cannot verify installed package file: '+str(path))
        return result.stdout.strip()
    expected=None;algorithm=None
    if manager=='pacman':
        owner=query(['pacman','-Qqo','--',str(path)])
        if not re.fullmatch(r'[A-Za-z0-9@._+\-]+',owner):raise ValueError('Ambiguous package owner')
        details=query(['pacman','-Q','--',owner]).split()
        if len(details)!=2 or details[0]!=owner:raise ValueError('Ambiguous installed package version')
        mtree=Path('/var/lib/pacman/local')/(owner+'-'+details[1])/'mtree'
        with gzip.open(mtree,'rt') as stream:
            for line in stream:
                fields=line.split()
                if fields and fields[0]=='./'+str(path).lstrip('/'):
                    expected=next((field.partition('=')[2] for field in fields[1:] if field.startswith('sha256digest=')),None)
                    break
        algorithm='sha256'
    elif manager=='apt-get':
        owners=query(['dpkg-query','-S',str(path)]).splitlines()
        if len(owners)!=1 or ': ' not in owners[0]:raise ValueError('Ambiguous package owner')
        package=owners[0].split(': ',1)[0];owner=package.split(':',1)[0]
        if not re.fullmatch(r'[A-Za-z0-9.+\-]+(?::[A-Za-z0-9_\-]+)?',package):raise ValueError('Invalid package owner')
        files=[Path('/var/lib/dpkg/info')/(package+'.md5sums'),Path('/var/lib/dpkg/info')/(owner+'.md5sums')]
        for item in files:
            if item.is_file():
                for line in item.read_text().splitlines():
                    fields=line.split(maxsplit=1)
                    if len(fields)==2 and fields[1]==str(path).lstrip('/'):expected=fields[0]
        if expected is None:
            for line in query(['dpkg-query','-W','-f=${Conffiles}',package]).splitlines():
                fields=line.split()
                if len(fields)>=2 and fields[0]==str(path):expected=fields[1]
        algorithm='md5'
    elif manager=='dnf':
        owner=query(['rpm','-qf','--qf','%{NAME}\n',str(path)])
        if not re.fullmatch(r'[A-Za-z0-9._+\-]+',owner):raise ValueError('Ambiguous package owner')
        for line in query(['rpm','-q','--dump',owner]).splitlines():
            fields=line.split()
            if len(fields)>=4 and fields[0]==str(path):expected=fields[3];break
        algorithm={32:'md5',40:'sha1',64:'sha256',128:'sha512'}.get(len(expected or ''))
    else:raise ValueError('Unsupported package manager')
    if not expected or not algorithm or hashlib.new(algorithm,data).hexdigest()!=expected.lower():
        raise ValueError('Package startup content is modified or cannot be verified: '+str(path))
    return {'package':owner,'sha256':hashlib.sha256(data).hexdigest(),'verification':'installed-package-content'}


def reconcile_package_owners(review, before_audit=None, *, verify_package=None):
    from adws_install_startup import audit, owner_signature
    if review.get('schema_version')!=1 or review['conflicts']:raise ValueError('Package owner review has unresolved conflicts')
    baseline=before_audit or review['before_audit']
    current=audit(review['config_home'],review['niri_path'],**review['audit_options'])
    if current['unknown']:raise ValueError('Unknown startup owners after dependency installation')
    reduced=json.loads(json.dumps(current['owners']));changes=[]
    verifier=verify_package or package_file_identity
    for entry in review['entries']:
        path=Path(entry['source']);target=Path(entry['target'])
        if not (path.exists() or path.is_symlink()):continue
        if target.exists() or target.is_symlink():raise ValueError('A user XDG entry appeared after review: '+str(target))
        matching=[row for row in reduced.get(entry['component'],[]) if row['origin']=='xdg' and row['id']==str(path)]
        if not matching:continue  # The package entry is not active for this desktop.
        identity=verifier(path,review['manager'])
        if identity['package'] not in entry['allowed_package_owners']:raise ValueError('Unexpected package owns new startup: '+str(path))
        parser=configparser.ConfigParser(interpolation=None,strict=False);parser.read(path)
        row=parser['Desktop Entry'];argv=shlex.split(row.get('Exec',''))
        if row.get('Type')!='Application' or not argv or argv[0] not in ('fcitx5','/usr/bin/fcitx5'):
            raise ValueError('Unexpected command in package startup: '+str(path))
        if any(arg not in ('-d','--daemon','--replace') for arg in argv[1:]):raise ValueError('Unreviewed package startup arguments')
        for rows in reduced.values():rows[:]=[row for row in rows if not (row['origin']=='xdg' and row['id']==str(path))]
        content='# ADWS reviewed package startup: Niri ownership is configured separately.\n[Desktop Entry]\nType=Application\nName=Fcitx 5\nHidden=true\n'
        changes.append({**entry,'package_identity':identity,'content':content})
    if owner_signature(reduced)!=owner_signature(baseline['owners']):
        raise ValueError('Unreviewed startup ownership change after package installation')
    return {'schema_version':1,'review':review,'changes':changes,
            'snapshot_targets':[row['target'] for row in changes],
            'source_hashes':current['source_hashes']}


def apply_reviewed_package_owners(proposal, backup_dir):
    from adws_atomic import replace_files
    from adws_install_startup import audit, owner_signature
    if proposal.get('schema_version')!=1:raise ValueError('Unsupported package startup proposal')
    for name,digest in proposal['source_hashes'].items():
        path=Path(name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Startup configuration changed after package review: '+name)
    writes={}
    for change in proposal['changes']:
        target=Path(change['target']);source=Path(change['source'])
        if target.exists() or target.is_symlink():raise ValueError('Refusing to overwrite a user XDG entry')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=change['package_identity']['sha256']:
            raise ValueError('Package startup changed before shadow creation')
        writes[target]=change['content'].encode()
    folder=Path(backup_dir);folder.mkdir(parents=True,exist_ok=True)
    (folder/'package-startup-proposal.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n')
    replace_files(writes)
    review=proposal['review'];after=audit(review['config_home'],review['niri_path'],**review['audit_options'])
    if after['unknown'] or owner_signature(after['owners'])!=owner_signature(review['before_audit']['owners']):
        raise ValueError('Startup ownership did not return to the reviewed baseline')
    return {'status':'configured' if writes else 'unchanged','shadows':[str(path) for path in writes]}

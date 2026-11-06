"""Audit startup ownership and add only missing, explicitly selected Niri starts.

Existing XDG entries/services are never stopped or disabled. Multiple owners are
reported as conflicts; this module does not guess which user startup to remove.
"""
import configparser
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import tempfile

from adws_install_package_owners import (reviewed_package_owners, reconcile_package_owners,
                                       apply_reviewed_package_owners)

BEGIN = '// ==== ADWS unified startup ===='
END = '// ==== ADWS unified startup END ===='
COMPONENTS = {'desktop', 'taskbar', 'input-method', 'clipboard-text', 'clipboard-image', 'notifications'}


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def components(argv):
    """Recognize exact executables, not substrings in arbitrary user commands."""
    if not argv: return set()
    name = Path(argv[0]).name
    if name in ('sh', 'bash', 'zsh') and len(argv) > 2 and argv[1] in ('-c', '-lc'):
        try: return components(shlex.split(argv[2]))
        except ValueError: return set()
    if name in ('sh', 'bash', 'zsh') and len(argv) > 1 and Path(argv[1]).name == 'adws':
        return components(argv[1:])
    if name == 'env':
        args = list(argv[1:])
        while args and ('=' in args[0] or args[0].startswith('-')): args.pop(0)
        return components(args)
    if name == 'adws' and any(x in argv for x in ('-s', '--start')):
        return {next(x for x in ('taskbar', 'desktop') if x in argv)} if any(x in argv for x in ('taskbar', 'desktop')) else {'desktop','taskbar'}
    if name in ('start-desktop-layer', 'desktop-layer'): return {'desktop'}
    if name == 'waybar' and any(Path(x).name == 'config-bottom.jsonc' for x in argv[1:]): return {'taskbar'}
    if name in ('fcitx5', 'fcitx', 'ibus-daemon'): return {'input-method'}
    if name in ('mako', 'dunst', 'swaync'): return {'notifications'}
    if name == 'wl-paste' and '--watch' in argv and 'cliphist' in argv:
        kind = next((argv[i+1] for i,a in enumerate(argv[:-1]) if a in ('--type','-t')), '')
        if kind in ('text','image'): return {'clipboard-'+kind}
        return {'clipboard-text','clipboard-image'}
    return set()


def audit(config_home, niri_path=None, enabled_units=None, unit_dirs=None, autostart_dirs=None, recognizer=None):
    config = Path(config_home).expanduser().absolute()
    niri = Path(niri_path) if niri_path else config/'niri/config.kdl'
    rows, unknown, visited, source_hashes = [], [], set(), {}
    niri_files, niri_includes = [], []
    recognize = recognizer or components
    def remember(path):
        try: source_hashes[str(Path(path).absolute())] = _hash(Path(path).read_bytes())
        except OSError: pass
    def record(origin, identity, argv, **metadata):
        found = recognize(argv)
        if found: rows.append({'origin':origin, 'id':str(identity), 'argv':argv, 'components':sorted(found), **metadata})
    def read_niri(path, missing_ok=False):
        path = path.resolve()
        if path in visited: return
        if len(visited) >= 64:
            unknown.append({'path':str(path),'reason':'include_limit'});return
        visited.add(path)
        if not path.exists():
            if not missing_ok and path != niri.resolve(): unknown.append({'path':str(path),'reason':'missing_include'})
            return
        try: text = path.read_text()
        except (OSError,UnicodeError) as exc:
            unknown.append({'path':str(path),'reason':str(exc)});return
        remember(path)
        niri_files.append(str(path))
        managed = False
        for number,line in enumerate(text.splitlines(),1):
            line = line.strip()
            if line == BEGIN:
                if managed: unknown.append({'path':str(path),'line':number,'reason':'nested_managed_startup'})
                managed = True; continue
            if line == END:
                if not managed: unknown.append({'path':str(path),'line':number,'reason':'unmatched_managed_startup'})
                managed = False; continue
            if line.startswith(('//','#','/-')): continue
            if not re.match(r'^(?:include|spawn-at-startup|spawn-sh-at-startup)\s+',line):continue
            if re.match(r'^include\s+',line):
                try:
                    from adws_install_kdl import include
                    name,optional=include(line);included=Path(name).expanduser()
                    included = (included if included.is_absolute() else path.parent/included).resolve()
                    niri_includes.append({'path':str(path),'line':number,'target':str(included),'optional':optional})
                    read_niri(included,missing_ok=optional)
                except ValueError:unknown.append({'path':str(path),'line':number,'reason':'unparsed_include'})
                continue
            try:
                from adws_install_kdl import spawn
                node,argv=spawn(line)
            except ValueError:
                unknown.append({'path':str(path),'line':number,'reason':'unparsed_startup_or_include'});continue
            if node == 'spawn-sh-at-startup':
                try:
                    args=shlex.split(argv[0])
                    if any(token in ('&&','||','|',';','&') for token in args):raise ValueError('Complex shell startup')
                    record('niri',f'{path}:{number}',args,managed_startup=managed,startup_node=node)
                except ValueError: unknown.append({'path':str(path),'line':number,'reason':'unparsed_shell_startup'})
            else: record('niri',f'{path}:{number}',argv,managed_startup=managed,startup_node=node)
        if managed: unknown.append({'path':str(path),'reason':'unclosed_managed_startup'})
    read_niri(niri)
    # User desktop entries shadow system entries with the same basename.
    desktops = {}
    for folder in (autostart_dirs if autostart_dirs is not None else (Path('/etc/xdg/autostart'),config/'autostart')):
        folder=Path(folder)
        for path in sorted(folder.glob('*.desktop')): desktops[path.name]=path
    for path in desktops.values():
        try:
            remember(path)
            parser=configparser.ConfigParser(interpolation=None,strict=False);parser.read(path)
            row=parser['Desktop Entry']
            if row.getboolean('Hidden',False) or not row.getboolean('X-GNOME-Autostart-enabled',True):continue
            only=set(filter(None,row.get('OnlyShowIn','').lower().split(';')))
            if only and not only.intersection({'niri','adws'}):continue
            if set(row.get('NotShowIn','').lower().split(';')).intersection({'niri','adws'}):continue
            record('xdg',path,shlex.split(row.get('Exec','')))
        except (OSError,ValueError,configparser.Error,KeyError) as exc:
            unknown.append({'path':str(path),'reason':str(exc)})
    directories=[Path(p) for p in (unit_dirs or [config/'systemd/user',
        Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'systemd/user',
        Path('/etc/systemd/user'),Path('/usr/lib/systemd/user')])]
    if enabled_units is None:
        # A fresh install may have no user D-Bus/systemd manager yet. Enablement
        # is persisted as filesystem links and does not require querying one.
        enabled_units=[]
        for directory in directories:
            for mask in sorted(directory.glob('*.service')):
                if mask.is_symlink() and mask.resolve()==Path('/dev/null'):enabled_units.append(mask.name)
            for pattern in ('*.wants/*.service','*.requires/*.service'):
                for link in sorted(directory.glob(pattern)):
                    if link.is_symlink():enabled_units.append(link.name)
        enabled_units=list(dict.fromkeys(enabled_units))
    seen_services=set()
    for name in enabled_units:
        if '/' in name or not name.endswith('.service'):continue
        path=next((folder/name for folder in directories if (folder/name).exists() or (folder/name).is_symlink()),None)
        if path is None:
            unknown.append({'path':name,'reason':'enabled_service_definition_unavailable'});continue
        masked=path.is_symlink() and path.resolve()==Path('/dev/null')
        if masked:
            underlying=next((folder/name for folder in directories if (folder/name).is_file() and (folder/name).resolve()!=Path('/dev/null')),None)
            if underlying is None:continue
            path=underlying
        canonical=path.resolve()
        if canonical in seen_services and not masked:continue
        seen_services.add(canonical)
        try:
            remember(path)
            parser=configparser.ConfigParser(interpolation=None,strict=False);parser.read(path)
            command=parser.get('Service','ExecStart',fallback='')
            if masked:
                if recognize(shlex.split(command.lstrip('-@:+!'))):
                    unknown.append({'path':name,'reason':'masked_component_requires_review'})
                continue
            record('systemd',name,shlex.split(command.lstrip('-@:+!')))
            if recognize(shlex.split(command.lstrip('-@:+!'))) and list((config/'systemd/user'/(name+'.d')).glob('*.conf')):
                unknown.append({'path':name,'reason':'service_dropins_require_review'})
        except (OSError,ValueError,configparser.Error) as exc:
            unknown.append({'path':str(path),'reason':str(exc)})
    component_keys=COMPONENTS | {key for row in rows for key in row['components']}
    owners={component:[row for row in rows if component in row['components']] for component in component_keys}
    return {'schema_version':1,'niri_path':str(niri),'owners':owners,'unknown':unknown,
            'source_hashes':source_hashes,'niri_files':niri_files,'niri_includes':niri_includes,
            'conflicts':[{'component':c,'owners':rows} for c,rows in owners.items() if len(rows)>1]}


def owner_signature(owners):
    """Compare actual ownership while keeping line numbers purely diagnostic.

    Replacing our own rules with an include can shift unchanged startup lines.
    Keep filename, executable arguments and multiplicity; never collapse owners
    into a set, which would conceal a newly duplicated start.
    """
    result={}
    for component,rows in owners.items():
        signatures=[]
        for row in rows:
            identity=row['id']
            if row['origin']=='niri':
                path,separator,line=identity.rpartition(':')
                if separator and line.isdigit():identity=path
            signatures.append(json.dumps([row['origin'],identity,row['argv'],sorted(row['components']),
                                          row.get('managed_startup',False),row.get('startup_node')],ensure_ascii=False))
        result[component]=sorted(signatures)
    return result


def relocation_evidence(source_migration):
    """Recheck the registered installation, never infer ownership from a basename."""
    if not source_migration or not source_migration.get('previous_root'): return None
    if source_migration.get('conflicts'): raise ValueError('Source migration conflicts require review')
    old = Path(source_migration['previous_root'])
    new = Path(source_migration['root'])
    if not old.is_absolute() or not new.is_absolute(): raise ValueError('Installation roots must be absolute')
    if old == new: return None
    inventory = Path(source_migration['inventory_path'])
    expected = source_migration.get('source_hashes',{}).get(str(inventory))
    if not expected or inventory.is_symlink() or not inventory.is_file():
        raise ValueError('Registered installation evidence is unavailable')
    if _hash(inventory.read_bytes()) != expected:
        raise ValueError('Registered installation changed after review: '+str(inventory))
    if json.loads(inventory.read_text()).get('root') != str(old):
        raise ValueError('Registered installation root does not match relocation')
    return {'previous_root':str(old),'root':str(new),'inventory_path':str(inventory),
            'source_hashes':{str(inventory):expected}}


def verify_sources(hashes):
    for name, expected in hashes.items():
        try: actual = _hash(Path(name).read_bytes())
        except OSError: actual = None
        if actual != expected: raise ValueError('Startup source changed after review: '+name)


def literal_arguments(text, start=0):
    """Return JSON/KDL string values and spans, leaving nonliteral syntax to callers."""
    args, spans = [], []
    decoder = json.JSONDecoder(); index = start
    while index < len(text):
        while index < len(text) and text[index].isspace(): index += 1
        if index == len(text) or text[index] != '"': break
        value, end = decoder.raw_decode(text, index)
        if not isinstance(value,str) or '\0' in value: raise ValueError('Invalid literal argument')
        args.append(value); spans.append((index,end)); index = end
    return args, spans, index


def validate_candidates(audited, files, validate):
    """Validate an uncommitted include graph; production files are never staged in place.

    Only changed files and their include ancestors need temporary copies. Each
    copy stays beside its source so unrelated relative resource paths still work.
    """
    needed = set(files); edges = audited.get('niri_includes',[])
    while True:
        parents = {row['path'] for row in edges if row['target'] in needed}
        if parents <= needed: break
        needed |= parents
    main = str(Path(audited['niri_path']).resolve())
    if main not in needed: raise ValueError('Changed startup file is not reachable from Niri configuration')
    temporary = {}
    try:
        for name in needed:
            path = Path(name); path.parent.mkdir(parents=True,exist_ok=True)
            fd, staged = tempfile.mkstemp(prefix='.adws-startup-',suffix='.kdl',dir=path.parent)
            os.close(fd); temporary[name] = Path(staged)
        for name, staged in temporary.items():
            original = Path(name)
            text = files[name] if name in files else original.read_text()
            lines = text.splitlines(keepends=True)
            for index,line in enumerate(lines):
                if not re.match(r'^\s*include\s+',line):continue
                from adws_install_kdl import include
                child,optional=include(line);child=Path(child).expanduser()
                target=str((child if child.is_absolute() else original.parent/child).resolve())
                if target in temporary:
                    # These copies are validation-only. The committed include
                    # syntax and paths remain byte-for-byte unchanged.
                    lines[index] = 'include '+('optional=true ' if optional else '')+json.dumps(str(temporary[target]),ensure_ascii=False)+'\n'
            staged.write_text(''.join(lines))
        validate(temporary[main])
    finally:
        for path in temporary.values(): path.unlink(missing_ok=True)


def plan(config_home, commands, niri_path=None, enabled_units=None, unit_dirs=None, autostart_dirs=None, *, source_migration=None, add_missing=True):
    """commands maps chosen components to argv; existing single owners are kept."""
    if set(commands)-COMPONENTS: raise ValueError('Unknown startup component')
    result=audit(config_home,niri_path,enabled_units,unit_dirs,autostart_dirs)
    result['audit_options']={'enabled_units':list(enabled_units) if enabled_units is not None else None,
                             'unit_dirs':[str(p) for p in unit_dirs] if unit_dirs is not None else None,
                             'autostart_dirs':[str(p) for p in autostart_dirs] if autostart_dirs is not None else None}
    result['config_home']=str(Path(config_home).absolute())
    result['commands']={k:list(v) for k,v in commands.items()}
    result['add_missing']=bool(add_missing)
    result['additions']=[];result['preserved']=[];result['replacements']=[]
    result['migration_source_hashes']={};result['source_migration']=None
    try: evidence = relocation_evidence(source_migration)
    except (OSError,ValueError,KeyError) as error:
        result['conflicts'].append({'kind':'installation-source','detail':str(error)});evidence=None
    if evidence:
        result['source_migration']=evidence
        result['migration_source_hashes']=evidence['source_hashes']
    for component,argv in commands.items():
        if not argv or not all(isinstance(x,str) and '\0' not in x and '\n' not in x for x in argv):raise ValueError('Invalid startup command')
        if component not in components(argv):raise ValueError('Command does not start selected component: '+component)
        existing=result['owners'][component]
        if existing:
            moved = False
            if evidence and component in ('desktop','taskbar') and len(existing)==1:
                owner=existing[0];old_script=str(Path(evidence['previous_root'])/'adws');new_script=str(Path(evidence['root'])/'adws')
                expected=[old_script if value==new_script else value for value in argv]
                if owner['argv']==list(argv): pass
                elif (owner['origin']=='niri' and owner.get('managed_startup') and owner.get('startup_node')=='spawn-at-startup'
                      and list(argv).count(new_script)==1 and owner['argv']==expected):
                    name,_,number=owner['id'].rpartition(':')
                    result['replacements'].append({'component':component,'path':name,'line':int(number),
                                                  'before':owner['argv'],'after':list(argv)})
                    moved=True
                else:
                    result['conflicts'].append({'component':component,'kind':'unmanaged-source-relocation','owner':owner,
                        'detail':'Existing startup is not the unchanged ADWS-managed command for the registered source; preserve and review.'})
            if not moved:result['preserved'].append(component)
        elif add_missing:result['additions'].append({'component':component,'argv':list(argv)})
    path=Path(result['niri_path']);result['before_sha256']=_hash(path.read_bytes()) if path.exists() else None
    result['snapshot_targets']=list(dict.fromkeys([row['path'] for row in result['replacements']]+([str(path.resolve())] if result['additions'] else [])))
    return result


def apply(plan, backup_dir, validate):
    """Append reviewed missing starts, validating full Niri config before replace.

    validate(temp_path) must raise on rejection. No services are started here;
    callers may choose a subsequent login/session activation as a separate step.
    """
    if plan.get('schema_version')!=1:raise ValueError('Unsupported startup plan')
    if plan['conflicts'] or plan['unknown']:raise ValueError('Startup ownership conflicts/unknowns require review')
    now=audit(plan['config_home'],plan['niri_path'],**plan.get('audit_options',{}))
    if now['owners']!=plan['owners'] or now['unknown'] or now['conflicts']:
        raise ValueError('Startup ownership changed after review')
    verify_sources(plan.get('source_hashes',{}))
    relocation_evidence(plan.get('source_migration'))
    if not plan['additions'] and not plan.get('replacements'):return {'status':'unchanged','preserved':plan['preserved']}
    path=Path(plan['niri_path']).resolve()
    before=path.read_bytes() if path.exists() else None
    if (_hash(before) if before is not None else None)!=plan['before_sha256']:raise ValueError('Niri config changed after review')
    text=before.decode() if before else ''
    files={}
    for row in plan.get('replacements',[]):
        name=row['path'];source=files.get(name,Path(name).read_text());source_lines=source.splitlines(keepends=True)
        line=source_lines[row['line']-1]
        match=re.match(r'^\s*spawn-at-startup\s+',line)
        if not match: raise ValueError('Managed startup is no longer a literal command')
        args,spans,_=literal_arguments(line,match.end())
        if args!=row['before']:raise ValueError('Managed startup arguments changed')
        for index in reversed(range(len(args))):
            if args[index]!=row['after'][index]:
                start,end=spans[index];line=line[:start]+json.dumps(row['after'][index],ensure_ascii=False)+line[end:]
        source_lines[row['line']-1]=line;files[name]=''.join(source_lines)
    text=files.get(str(path),text)
    lines=[];seen=set()
    for addition in plan['additions']:
        argv=addition['argv'];key=tuple(argv)
        if key in seen:continue
        seen.add(key)
        lines.append('spawn-at-startup '+' '.join(json.dumps(v,ensure_ascii=False) for v in argv))
    if lines:
        text=text.rstrip()+'\n\n'+BEGIN+'\n'+'\n'.join(lines)+'\n'+END+'\n'
        files[str(path)]=text
    validate_candidates(plan,files,validate)
    verify_sources(plan.get('source_hashes',{}));relocation_evidence(plan.get('source_migration'))
    if (path.read_bytes() if path.exists() else None)!=before:raise ValueError('Niri config changed during validation')
    directory=Path(backup_dir);directory.mkdir(parents=True,exist_ok=False)
    if before is not None:(directory/'config.kdl').write_bytes(before)
    manifest=[]
    for index,name in enumerate(files):
        target=Path(name);backup=directory/('source-'+str(index)+'.kdl')
        if target.exists():backup.write_bytes(target.read_bytes())
        manifest.append({'path':name,'backup':str(backup) if target.exists() else None})
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    from adws_atomic import replace_files
    replace_files({Path(name):content.encode() for name,content in files.items()})
    return {'status':'configured','backup':str(directory),'additions':plan['additions'],
            'replacements':plan.get('replacements',[]),'activation':'next_login'}

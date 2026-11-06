"""Relocate known ADWS helper references without replacing personal bar styling.

Plans contain exact file content and hashes. This module never signals Waybar:
the outer installer stops/restarts only reviewed matching running profiles, with
their original session environment, before/after its configuration transaction.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

from adws_install_source_migration import _bytes
from adws_install_startup import relocation_evidence

SCHEMA = 1
COMMAND_KEYS = {'exec', 'exec-if', 'on-click', 'on-click-right', 'on-click-middle', 'on-scroll-up', 'on-scroll-down',
                'on-update', 'on-sigusr1', 'on-sigusr2'}


def _hash(value): return hashlib.sha256(value).hexdigest()


def _migration_evidence(proposal):
    if not proposal or not proposal.get('previous_root'): return None
    if proposal['previous_root'] != proposal['root']: return relocation_evidence(proposal)
    # A later reinstall at the same path can still repair a proven older root.
    inventory=Path(proposal['inventory_path']);raw=_bytes(inventory)
    expected=proposal.get('source_hashes',{}).get(str(inventory))
    if proposal.get('conflicts') or raw is None or not expected or _hash(raw)!=expected or json.loads(raw).get('root')!=proposal['previous_root']:
        raise ValueError('Registered installation evidence changed')
    return {key:proposal[key] for key in ('previous_root','root','inventory_path','source_hashes')}


def _historical_roots(evidence):
    """Only actual transaction snapshots prove a former registered source root.

    Follow neither arbitrary manifest paths nor symlinks. Reading a backup never
    executes its code. Only used evidence is added to the approved plan hashes.
    """
    inventory=Path(evidence['inventory_path']);folder=inventory.parent.parent/'adws-install-backups'
    roots={Path(evidence['previous_root']):{'kind':'current-installation','source_hashes':evidence['source_hashes']}}
    if not folder.exists():return roots
    from adws_install_source_migration import _safe_path
    _safe_path(folder)
    if folder.stat().st_uid!=os.getuid():raise ValueError('Installer backup directory has another owner')
    directories=sorted(folder.glob('install-*'),key=lambda p:p.name,reverse=True)
    total=0
    for directory in directories[:256]:
        if directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid!=os.getuid():continue
        manifest=directory/'manifest.json'
        try:
            if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_uid!=os.getuid() or manifest.stat().st_size>1024*1024:continue
            raw=_bytes(manifest);total+=len(raw)
            if total>16*1024*1024:break
            entries=json.loads(raw)
            if not isinstance(entries,list) or len(entries)>1000:continue
            for row in entries:
                if not isinstance(row,dict) or row.get('path')!=str(inventory) or row.get('existed') is not True:continue
                saved=Path(row.get('backup',''))
                if saved.parent!=directory or not saved.name.isdecimal():continue
                if saved.is_symlink() or not saved.is_file() or saved.stat().st_uid!=os.getuid() or saved.stat().st_size>1024*1024:continue
                content=_bytes(saved);data=json.loads(content)
                old=data.get('root') if isinstance(data,dict) else None
                if not isinstance(old,str) or not Path(old).is_absolute() or len(Path(old).parts)<3:continue
                old=Path(old)
                if old!=old.resolve():continue
                roots.setdefault(old,{'kind':'installer-snapshot','manifest':str(manifest),'record':str(saved),
                    'source_hashes':{str(manifest):_hash(raw),str(saved):_hash(content)}})
        except (OSError,ValueError,TypeError,RecursionError):continue
    return roots


def _command_origin(value,roots,new):
    if not any(str(root) in value for root in roots) and '/tools/adws_' not in value and not re.search(r'/adws(?:[\s\'\"]|$)',value):return None
    words=shell_literals(value)
    if not words: return None
    argv=[row[0] for row in words]
    index=1 if Path(argv[0]).name in ('sh','bash') or re.fullmatch(r'python(?:\d+(?:\.\d+)*)?',Path(argv[0]).name) else 0
    if len(argv)<=index:raise ValueError('Unknown old-source command')
    script=Path(argv[index])
    root=script.parent if script.name=='adws' else script.parent.parent if script.parent.name=='tools' and script.name.startswith('adws_') else None
    if root==new:return None
    if root not in roots:raise ValueError('Unproven installation root in top-bar command: '+str(script))
    return root


def shell_literals(command):
    """Parse a single literal argv with offsets; reject shell execution syntax."""
    result = []; index = 0
    while index < len(command):
        while index < len(command) and command[index] in ' \t': index += 1
        if index == len(command): break
        start = index; quote = None
        while index < len(command):
            char = command[index]
            if quote == "'":
                if char == "'": quote = None
                index += 1; continue
            if char == '\\':
                if index+1 >= len(command) or command[index+1] == '\n': raise ValueError('Unsupported shell escape')
                index += 2; continue
            if char in '$`' or char in '\r\n': raise ValueError('Shell expansion requires review')
            if quote == '"':
                if char == '"': quote = None
                index += 1; continue
            if char in ('"', "'"): quote = char; index += 1; continue
            if char in ';&|()<>{}': raise ValueError('Compound shell command requires review')
            if char in ' \t': break
            index += 1
        if quote: raise ValueError('Unterminated shell quote')
        raw = command[start:index]; values = shlex.split(raw)
        if len(values) != 1: raise ValueError('Ambiguous shell argument')
        result.append((values[0], start, index))
    return result


def _allowed(script, args):
    if script == 'adws':
        return args in (['start-menu'], ['config']) or len(args)==3 and args[:2]==['config','--tab'] and args[2] in {'wallpaper','network','bluetooth','power','waybar'}
    if script == 'tools/adws_launcher.py': return args == ['--terminal']
    if script in ('tools/adws_color_picker.py','tools/adws_color_scheme.py','tools/adws_cava.py'): return not args
    if script == 'tools/adws_clipboard.py': return args in ([], ['--watch-start'])
    if script == 'tools/adws_gnome_menu.py': return args in (['system'],['calendar'],['system','--preview'],['calendar','--preview'])
    if script == 'tools/adws_topbar.py': return args == ['--stop-preview']
    if script == 'tools/adws_topbar_update.py':
        return (not args or len(args)==2 and args[0]=='--manager' and args[1] in ('auto','yay','paru')
                or len(args)==4 and args[:3]==['--manager','custom','--command'])
    if script == 'tools/adws_topbar_controls.py':
        return (len(args)==1 and args[0] in ('poweroff','reboot','logout','lock','night','toggle','state')
                or len(args)==3 and args[:2]==['brightness','--value'] and args[2].isdigit() and 0<=int(args[2])<=100)
    if script == 'tools/adws_quick_controls.py':
        return (args in (['sound'],['sound','--panel'],['brightness','--panel'])
                or len(args)==3 and args[:2]==['brightness','--step'] and re.fullmatch(r'-?\d+',args[2]) and -100<=int(args[2])<=100)
    return False


def command_replacement(value, old, new):
    if str(old) not in value: return None
    parts = shell_literals(value); argv = [row[0] for row in parts]
    if not argv: return None
    index = 0
    if Path(argv[0]).name in ('bash','sh') or re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', Path(argv[0]).name): index = 1
    if len(argv) <= index: raise ValueError('Unrecognized old-source command')
    try: relative = Path(argv[index]).relative_to(old).as_posix()
    except ValueError: raise ValueError('Old-source reference is not the known executable argument')
    interpreter = Path(argv[0]).name if index else None
    if relative == 'adws' and interpreter and interpreter not in ('sh','bash'):
        raise ValueError('Unknown ADWS launcher wrapper')
    if relative != 'adws' and index and not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', interpreter):
        raise ValueError('Unknown Python helper wrapper')
    if not _allowed(relative,argv[index+1:]): raise ValueError('Unknown helper or custom arguments need review: ' + relative)
    if any(str(old) in word for i,word in enumerate(argv) if i != index):
        raise ValueError('Additional old-source arguments require review')
    destination = new/relative
    if not destination.is_file(): raise ValueError('New helper is missing: ' + str(destination))
    _,start,end=parts[index]
    updated=value[:start]+shlex.quote(str(destination))+value[end:]
    return updated, relative


def json_strings(text):
    """Return leaf paths/string spans while rejecting duplicate JSONC keys."""
    from adws_waybar import tokens, decode
    decode(text); items=tokens(text); leaves=[]
    def walk(i,path):
        value,start,end=items[i]
        if value=='{':
            keys=set();i+=1
            while items[i][0]!='}':
                key=json.loads(items[i][0])
                if not isinstance(key,str) or key in keys:raise ValueError('Duplicate/invalid Waybar key')
                keys.add(key)
                if items[i+1][0]!=':':raise ValueError('Invalid Waybar property')
                i=walk(i+2,path+(key,))
                if items[i][0]==',':i+=1
                elif items[i][0]!='}':raise ValueError('Invalid Waybar object')
            return i+1
        if value=='[':
            i+=1;index=0
            while items[i][0]!=']':
                i=walk(i,path+(index,));index+=1
                if items[i][0]==',':i+=1
                elif items[i][0]!=']':raise ValueError('Invalid Waybar array')
            return i+1
        if value.startswith('"'):leaves.append((path,json.loads(value),start,end))
        return i+1
    if walk(0,())!=len(items):raise ValueError('Unparsed Waybar content')
    return leaves


def _edits(text,edits):
    for start,end,value in sorted(edits,reverse=True):text=text[:start]+value+text[end:]
    return text


def _css_value(raw):
    if raw[:1] in ('"',"'"):
        if raw[-1:]!=raw[:1]:raise ValueError('Invalid CSS string')
        raw=raw[1:-1]
    # ADWS's generated CSS quotes only backslashes/quotes; nonliteral escapes
    # need a separate review rather than rewriting an incorrectly decoded path.
    if re.search(r'\\(?:[0-9a-fA-F]|\n|\r)',raw):raise ValueError('Complex CSS escape requires review')
    return re.sub(r'\\(.)',r'\1',raw)


def plan(config_home, source_migration, *, include_foot=True):
    config=Path(config_home).expanduser().absolute()
    result={'schema_version':SCHEMA,'files':{},'source_hashes':{},'snapshot_targets':[],
            'replacements':[],'conflicts':[],'restart_profiles':[],'limitations':[],
            'source_migration':None,'reviewed_roots':[],'status':'none'}
    try:evidence=_migration_evidence(source_migration)
    except (OSError,ValueError) as exc:
        result['conflicts'].append({'kind':'source-evidence','detail':str(exc)});result['status']='blocked';return result
    if not evidence:return result
    result['source_migration']=evidence
    old,new=Path(evidence['previous_root']),Path(evidence['root'])
    try:origins=_historical_roots(evidence)
    except (OSError,ValueError) as exc:
        result['conflicts'].append({'kind':'source-history','detail':str(exc)});result['status']='blocked';return result
    def use_origin(origin):
        proof=origins[origin]
        if not any(row['root']==str(origin) for row in result['reviewed_roots']):
            result['reviewed_roots'].append({'root':str(origin),**proof})
            result['source_hashes'].update(proof['source_hashes'])
    read_cache={};total=0
    def read(path,optional=False):
        nonlocal total
        path=Path(path).absolute()
        if str(path) in read_cache:return read_cache[str(path)]
        if len(read_cache)>=64:raise ValueError('Too many top-bar configuration references')
        raw=_bytes(path)
        result['source_hashes'][str(path)]=_hash(raw) if raw is not None else None
        if raw is None:
            if optional:return None
            raise ValueError('Referenced top-bar file is missing: '+str(path))
        total+=len(raw)
        if total>32*1024*1024:raise ValueError('Top-bar configuration is too large')
        text=raw.decode('utf-8');read_cache[str(path)]=text;return text
    def remember(path,before,after,edits):
        if before!=after:
            result['files'][str(path)]=after
            result['replacements'].extend({'path':str(path),**row} for row in edits)
    def reference(value,parent):
        path=Path(os.path.expandvars(value)).expanduser()
        path=path if path.is_absolute() else parent/path
        if any(c in str(path) for c in '*?[]'):raise ValueError('Wildcard top-bar include needs review')
        if any(path.resolve().is_relative_to(root) for root in set(origins)|{new}):raise ValueError('Custom resource/include in installation source needs review: '+str(path))
        return path.absolute()
    visited=set()
    def visit_json(path):
        path=Path(path).absolute()
        if str(path) in visited:return
        visited.add(str(path));text=read(path);edits=[];changes=[]
        for key,value,start,end in json_strings(text):
            field=key[-1] if key else None
            if field=='include' or len(key)>1 and key[-2]=='include':
                visit_json(reference(value,path.parent));continue
            if field not in COMMAND_KEYS:continue
            origin=_command_origin(value,origins,new)
            if origin is None:continue
            use_origin(origin)
            updated,script=command_replacement(value,origin,new)
            edits.append((start,end,json.dumps(updated,ensure_ascii=False)))
            changes.append({'kind':'command','field':list(key),'script':script,'before':value,'after':updated})
        updated=_edits(text,edits)
        json_strings(updated)
        remember(path,text,updated,changes)
    css_seen=set()
    css_tokens=re.compile(r'/\*[\s\S]*?\*/|url\(\s*(?P<url>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^)\s]+)\s*\)|@import\s+(?P<import>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')',re.I)
    def visit_css(path):
        path=Path(path).absolute()
        if str(path) in css_seen:return
        css_seen.add(str(path));text=read(path);edits=[];changes=[]
        from adws_waybar import css_string
        for match in css_tokens.finditer(text):
            if match.group().startswith('/*'):continue
            group='import' if match.group('import') is not None else 'url'
            raw=match.group(group);value=_css_value(raw)
            imported=group=='import' or bool(re.search(r'@import\s*$',text[:match.start()],re.I))
            if imported:
                if value.startswith(('https:','http:','resource:','data:')):continue
                visit_css(reference(value,path.parent));continue
            if value.startswith(('https:','http:','resource:','data:')):continue
            suffix=next((Path('config/waybar')/('arrow-'+side+'-symbolic.svg') for side in ('left','right')
                         if value.endswith('/config/waybar/arrow-'+side+'-symbolic.svg')),None)
            if suffix is None:
                if any(str(root) in value for root in origins):raise ValueError('Unknown CSS resource in old installation needs review: '+value)
                continue
            origin=Path(value).parents[2]
            if origin==new:continue
            if origin not in origins:raise ValueError('Unproven installation root in CSS resource: '+value)
            use_origin(origin);relative=str(suffix)
            target=new/relative
            if not target.is_file():raise ValueError('New top-bar arrow is missing: '+str(target))
            edits.append((*match.span(group),css_string(str(target))))
            changes.append({'kind':'css-url','before':value,'after':str(target)})
        remember(path,text,_edits(text,edits),changes)
    try:
        profile_path=config/'adws/waybar-top.json';profile_text=read(profile_path,optional=True)
        profile=json.loads(profile_text) if profile_text is not None else {}
        if not isinstance(profile,dict):raise ValueError('Invalid top-bar profile')
        default=next((config/'waybar'/n for n in ('config','config.jsonc') if (config/'waybar'/n).is_file()),config/'waybar/config.jsonc')
        selected=reference(profile.get('config',str(default)),config)
        style=reference(profile.get('style',str(config/'waybar/style.css')),config)
        if selected.name=='config-bottom.jsonc' or style.name=='style-bottom.css':raise ValueError('Top-bar profile points to the bottom taskbar')
        if selected.is_file():
            visit_json(selected)
            if style.is_file():visit_css(style)
            if result['files']:result['restart_profiles'].append({'config':str(selected),'style':str(style)})
        if include_foot:
            hook=config/'adws/palette/foot-hook.sh';body=read(hook,optional=True)
            if body is not None and '/tools/adws_palette_sync.py' in body:
                from adws_palette_sync import MARKER, registration_plan
                registry=config/'adws/palette-sync.json';registered=json.loads(read(registry))
                if not body.startswith(MARKER+'\n') or 'foot' not in registered.get('targets',[]) or registered.get('foot_shell') not in ('bash','zsh'):
                    raise ValueError('Unrecognized Foot hook ownership requires review')
                # Match the whole known generated template before touching the
                # script token; never rewrite a user-edited shell program.
                matches=[]
                for match in re.finditer(r'(?m)^   (.+) --parent "\$\$" >/dev/null 2>&1 &$',body):
                    words=shell_literals(match[1]);argv=[row[0] for row in words]
                    if len(argv)==4 and re.fullmatch(r'python(?:\d+(?:\.\d+)*)?',Path(argv[0]).name) and argv[2:]==['--watch-foot',str(config/'adws/palette/foot.json')] and argv[1].endswith('/tools/adws_palette_sync.py'):
                        matches.append((match,words))
                if len(matches)!=1:raise ValueError('Modified Foot hook command requires review')
                match,words=matches[0]
                script=words[1][0];origin=Path(script).parent.parent
                if origin==new:
                    result['snapshot_targets']=sorted(result['files'])
                    result['status']='ready' if result['files'] else 'none'
                    return result
                if origin not in origins:raise ValueError('Unproven installation root in Foot hook: '+str(origin))
                use_origin(origin)
                # Produce the canonical template through the same generator,
                # then compare after substituting only its interpreter/script.
                canonical=registration_plan(['foot'],config_home=config,home=registered.get('home',str(Path.home())),data_home=registered.get('data_home'),foot_shell=registered['foot_shell'])
                generated=next(row['content'] for row in canonical['files'] if row['path']==str(hook))
                import adws_palette_sync
                expected=generated.replace(shlex.quote(str(Path(adws_palette_sync.__file__).resolve())),shlex.quote(script),1)
                # The original Python path is an argv token, not arbitrary text.
                generated_python=shlex.quote(__import__('sys').executable)
                expected=expected.replace('   '+generated_python+' ', '   '+shlex.quote(words[0][0])+' ',1)
                if expected!=body:raise ValueError('User-edited Foot hook requires review')
                target=new/'tools/adws_palette_sync.py'
                if not target.is_file():raise ValueError('New Foot watcher is missing')
                start=match.start(1)+words[1][1];end=match.start(1)+words[1][2]
                updated=body[:start]+shlex.quote(str(target))+body[end:]
                remember(hook,body,updated,[{'kind':'foot-hook','before':script,'after':str(target)}])
                result['limitations'].append('Existing Foot watcher processes remain until their terminal closes; new terminal shells use the relocated hook.')
    except (OSError,ValueError,TypeError,KeyError,IndexError,StopIteration,RecursionError) as exc:
        result['conflicts'].append({'kind':'topbar-source-relocation','detail':str(exc)})
    result['snapshot_targets']=sorted(result['files'])
    result['status']='blocked' if result['conflicts'] else 'ready' if result['files'] else 'none'
    return result


def verify_before(proposal):
    if proposal.get('schema_version')!=SCHEMA or proposal.get('conflicts'):raise ValueError('Top-bar relocation requires a new reviewed plan')
    _migration_evidence(proposal.get('source_migration'))
    for name,digest in proposal['source_hashes'].items():
        raw=_bytes(Path(name))
        if (_hash(raw) if raw is not None else None)!=digest:raise ValueError('Top-bar source changed after review: '+name)
    return True


def apply(proposal, backup_dir):
    """Called after the caller stops matching bars, before inventory is changed."""
    verify_before(proposal)
    if not proposal['files']:return {'status':'unchanged','files':[],'restart_profiles':[]}
    backup=Path(backup_dir);backup.mkdir(parents=True,exist_ok=False)
    (backup/'plan.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n')
    for index,name in enumerate(proposal['files']):
        (backup/str(index)).write_bytes(Path(name).read_bytes())
    verify_before(proposal)
    from adws_atomic import replace_files
    replace_files({Path(name):text.encode() for name,text in proposal['files'].items()})
    return {'status':'relocated','backup':str(backup),'files':sorted(proposal['files']),
            'restart_profiles':proposal['restart_profiles'],'limitations':proposal['limitations']}

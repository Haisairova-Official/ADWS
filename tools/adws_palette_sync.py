"""Opt-in ADWS palette integration; never execute third-party Matugen hooks.

Protocols: https://sw.kovidgoyal.net/kitty/conf/ (SIGUSR1/includes)
https://alacritty.org/config-alacritty.html (imports/live_config_reload)
https://dunst-project.org/documentation/dunst/ (drop-ins), .../dunstctl/ (reload)
https://github.com/emersion/mako/blob/master/doc/makoctl.1.scd (reload)
https://man.archlinux.org/man/foot-ctlseqs.7.en (OSC 10/11/12/17/19)
"""
from __future__ import annotations
import argparse
import configparser
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import threading
import tomllib

SCHEMA = 1
TARGETS = ('kitty', 'alacritty', 'foot', 'mako', 'dunst', 'icons')
MARKER = '# ADWS managed palette'
BEGIN = '# BEGIN ADWS PALETTE'
END = '# END ADWS PALETTE'
DEFAULT_PALETTE = {'surface':'#202128', 'surface_container':'#292a32', 'surface_container_high':'#34353f',
    'on_surface':'#e5e1ec', 'on_surface_variant':'#c7c4d0', 'primary':'#c4b5fd',
    'on_primary':'#2e2058', 'outline_variant':'#484552', 'error':'#ffb4ab'}


def _digest(data): return hashlib.sha256(data).hexdigest()

def _config(): return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
def _data(): return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
def registry_path(config_home=None): return Path(config_home or _config())/'adws/palette-sync.json'


def _registry_snapshot(path):
    """Read bounded registration data without following a special-file input."""
    path=Path(path)
    if not path.exists():
        if path.is_symlink():raise ValueError('Palette registration is a dangling symlink')
        return None,{}
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>2*1024*1024:
        raise ValueError('Palette registration must be a small regular file')
    raw=path.read_bytes()
    if len(raw)>2*1024*1024:raise ValueError('Palette registration is too large')
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get('schema_version')!=SCHEMA:
        raise ValueError('Existing palette registration needs review')
    return raw,value


def _foot_hook_content(interpreter,script,palette_path):
    command=' '.join(shlex.quote(str(x)) for x in (interpreter,script,'--watch-foot',palette_path))
    return (MARKER+'\ncase "${TERM:-}" in foot*)\n'
            ' if [ -t 1 ] && { ADWS_FOOT_CURRENT_TTY=$(tty <&3 2>/dev/null); } 3>&1; then\n'
            '  if [ -n "$ADWS_FOOT_CURRENT_TTY" ] && { [ "$ADWS_FOOT_CURRENT_TTY" != "${ADWS_FOOT_PALETTE_TTY:-}" ] || [ -z "${ADWS_FOOT_PALETTE_PID:-}" ] || ! kill -0 "$ADWS_FOOT_PALETTE_PID" 2>/dev/null; }; then\n'
            f'   {command} --parent "$$" >/dev/null 2>&1 &\n'
            '   ADWS_FOOT_PALETTE_PID=$!; ADWS_FOOT_PALETTE_TTY=$ADWS_FOOT_CURRENT_TTY\n'
            '   export ADWS_FOOT_PALETTE_PID ADWS_FOOT_PALETTE_TTY\n  fi\n  unset ADWS_FOOT_CURRENT_TTY\n fi;;\nesac\n')


def _check_foot_hook(text,palette_path):
    """A marker alone never authorizes replacing a user-edited shell program."""
    matches=list(re.finditer(r'(?m)^   (.+) --parent "\$\$" >/dev/null 2>&1 &$',text))
    if len(matches)!=1:raise ValueError('User-edited Foot hook requires review')
    argv=shlex.split(matches[0][1])
    if (len(argv)!=4 or not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?',Path(argv[0]).name)
            or not Path(argv[1]).is_absolute() or not argv[1].endswith('/tools/adws_palette_sync.py')
            or argv[2:]!=['--watch-foot',str(palette_path)]
            or text!=_foot_hook_content(argv[0],argv[1],palette_path)):
        raise ValueError('User-edited Foot hook requires review')


def validate_palette(palette):
    if not isinstance(palette,dict) or not set(DEFAULT_PALETTE) <= set(palette): raise ValueError('Incomplete palette')
    if any(not re.fullmatch(r'[a-z][a-z0-9_]*', k) or not isinstance(v,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',v) for k,v in palette.items()):
        raise ValueError('Palette contains invalid colors')
    return palette


def render(target, palette, *, foot_section="colors-dark"):
    p = validate_palette(palette)
    foreground,background,accent=p['on_surface'],p['surface'],p['primary']
    if target=='kitty':
        return MARKER+'\n'+f'foreground {foreground}\nbackground {background}\ncursor {accent}\nselection_foreground {p["on_primary"]}\nselection_background {accent}\nactive_border_color {accent}\ninactive_border_color {p["outline_variant"]}\n'
    if target=='alacritty':
        return MARKER+'\n'+f'[colors.primary]\nforeground = "{foreground}"\nbackground = "{background}"\n[colors.cursor]\ntext = "{background}"\ncursor = "{accent}"\n[colors.selection]\ntext = "{p["on_primary"]}"\nbackground = "{accent}"\n'
    if target=='foot':
        if foot_section not in ('colors-dark','colors'):raise ValueError('Foot section must be resolved against the installed Foot parser')
        return MARKER+'\n'+f'[{foot_section}]\nforeground={foreground[1:]}\nbackground={background[1:]}\nselection-foreground={p["on_primary"][1:]}\nselection-background={accent[1:]}\n'
    if target=='mako':
        return MARKER+'\n'+f'background-color={p["surface_container"]}\ntext-color={foreground}\nborder-color={accent}\n'
    if target=='dunst':
        return MARKER+'\n'+''.join(f'[{section}]\nbackground="{p["surface_container"]}"\nforeground="{foreground}"\nframe_color="{p["error"] if section=="urgency_critical" else accent}"\n' for section in ('urgency_low','urgency_normal','urgency_critical'))
    raise ValueError('Unknown palette target')


def _path(path):
    path=Path(path).expanduser()
    if not path.is_absolute() or '\n' in str(path) or '\0' in str(path): raise ValueError('Invalid absolute configuration path')
    return path


def _block(text, line):
    if text.count(BEGIN)!=text.count(END) or text.count(BEGIN)>1:raise ValueError('Incomplete palette integration markers')
    text=re.sub(r'(?ms)^'+re.escape(BEGIN)+r'\n.*?^'+re.escape(END)+r'\n?', '', text)
    return text.rstrip()+'\n\n'+BEGIN+'\n'+line+'\n'+END+'\n'


def _alacritty(text, fragment, replace_colors=False):
    parsed=tomllib.loads(text)
    if 'import' in parsed:raise ValueError('Legacy Alacritty import format needs migration before palette integration')
    if parsed.get('general',{}).get('live_config_reload') is False:raise ValueError('Alacritty live_config_reload is disabled; enable it and restart explicitly')
    if 'colors' in parsed:
        if not replace_colors:raise ValueError('Alacritty has custom inline colors; explicit replace_colors approval is required')
        lines=text.splitlines(keepends=True);out=[];skip=False
        for line in lines:
            if re.match(r'^\s*\[',line):skip=bool(re.match(r'^\s*\[colors(?:\.|\])',line))
            if not skip:out.append(line)
        text=''.join(out)
        if 'colors' in tomllib.loads(text):raise ValueError('Inline color object cannot be safely removed automatically')
    parsed=tomllib.loads(text);imports=parsed.get('general',{}).get('import',[])
    if not isinstance(imports,list) or not all(isinstance(x,str) for x in imports):raise ValueError('Invalid Alacritty imports')
    imports=[x for x in imports if x!=str(fragment)]+[str(fragment)]
    addition='import = '+json.dumps(imports)+'\n'
    match=re.search(r'(?m)^\s*\[general\]\s*$',text)
    if match:
        end=re.search(r'(?m)^\s*\[',text[match.end():]);limit=match.end()+end.start() if end else len(text)
        section=text[match.end():limit]
        existing=re.search(r'(?ms)^\s*import\s*=\s*\[.*?\]',section)
        if existing:section=section[:existing.start()]+'\n'+addition+section[existing.end():]
        else:section='\n'+addition+section
        text=text[:match.end()]+section+text[limit:]
    else:text=text.rstrip()+'\n\n[general]\n'+addition
    checked=tomllib.loads(text)
    if checked.get('general',{}).get('import')!=imports:raise ValueError('Alacritty import could not be merged')
    return text


def registration_plan(targets, *, config_home=None, data_home=None, home=None,
                      base_icon_theme=None, replace_colors=False, foot_shell=None, palette=None, foot_format_policy="auto"):
    """Prepare exact file edits and refresh policy; callers review before register."""
    selected=list(dict.fromkeys(targets))
    if set(selected)-set(TARGETS):raise ValueError('Unknown palette target')
    config=_path(config_home or _config()).resolve();data=_path(data_home or _data()).resolve();home=_path(home or Path.home()).resolve()
    p=validate_palette(palette or DEFAULT_PALETTE)
    result={'schema_version':SCHEMA,'config_home':str(config),'data_home':str(data),'home':str(home),
            'targets':selected,'base_icon_theme':base_icon_theme,'foot_shell':foot_shell,'files':[],
            'conflicts':[],'limitations':[],'managed':{},'foot_format_policy':foot_format_policy}
    registration=registry_path(config)
    try:
        registry_raw,existing=_registry_snapshot(registration)
        result['registry_before']=_digest(registry_raw) if registry_raw is not None else None
        result['registry_resolved']=str(registration.resolve())
        if 'foot' in selected and foot_shell is None and 'foot' in existing.get('targets',[]):
            previous_shell=existing.get('foot_shell')
            if previous_shell not in (None,'bash','zsh'):raise ValueError('Existing Foot shell choice needs review')
            if previous_shell:
                if existing.get('config_home')!=str(config) or existing.get('home')!=str(home):
                    raise ValueError('Existing Foot registration belongs to another home')
                foot_shell=previous_shell;result['foot_shell']=foot_shell
                result['foot_shell_policy']='preserve-registered'
    except (OSError,UnicodeError,ValueError,TypeError) as error:
        result['conflicts'].append({'target':'registration','reason':str(error)})
        return result
    def add(path,content,managed=False):
        path=_path(path);resolved=path.resolve()
        old=resolved.read_bytes() if resolved.exists() else None
        if managed and old is not None and not old.decode('utf-8').startswith(MARKER):raise ValueError('Managed fragment collides with a user file: '+str(path))
        result['files'].append({'path':str(path),'resolved':str(resolved),'before':_digest(old) if old is not None else None,'content':content})
    for target in selected:
        try:
            if target=='icons':
                if not isinstance(base_icon_theme,str) or not re.fullmatch(r'[\w .+-]+',base_icon_theme) or base_icon_theme.startswith('ADWS-Palette-'):
                    raise ValueError('Select the existing base icon theme explicitly')
                result['managed']['icons']={'base':base_icon_theme};continue
            fragment=config/'adws/palette'/('colors.'+{'kitty':'kitty.conf','alacritty':'alacritty.toml','foot':'foot.ini','mako':'mako.conf','dunst':'dunst.conf'}[target])
            if target=='dunst':fragment=config/'dunst/dunstrc.d/99-adws-palette.conf'
            add(fragment,render(target,p),managed=True)
            if target=='kitty':
                main=config/'kitty/kitty.conf';text=main.read_text() if main.exists() else ''
                if re.search(r'(?m)^\s*geninclude\s',text):raise ValueError('Kitty geninclude would execute user hooks during reload; keep manual integration')
                add(main,_block(text,'include '+str(fragment)))
            elif target=='alacritty':
                main=config/'alacritty/alacritty.toml';text=main.read_text() if main.exists() else ''
                add(main,_alacritty(text,fragment,replace_colors))
            elif target=='mako':
                main=config/'mako/config';text=main.read_text() if main.exists() else ''
                section=re.search(r'(?m)^\s*\[',text)
                before,after=(text[:section.start()],text[section.start():]) if section else (text,'')
                add(main,_block(before,'include='+str(fragment))+after)
            elif target=='dunst':
                main=config/'dunst/dunstrc'
                if not main.exists():add(main,'# ADWS notification configuration\n[global]\n')
                if any(p.name>fragment.name for p in fragment.parent.glob('*.conf')):raise ValueError('A later Dunst user drop-in may override the palette')
            elif target=='foot':
                if foot_format_policy!='auto':raise ValueError('Foot requires the reviewed automatic installed-parser format policy')
                hook=config/'adws/palette/foot-hook.sh';palette_path=config/'adws/palette/foot.json'
                if hook.exists() or hook.is_symlink():
                    _check_foot_hook(hook.read_text(),palette_path)
                    if foot_shell not in ('bash','zsh'):
                        raise ValueError('Existing Foot hook has no matching shell registration; select its shell for review')
                result['foot_format_alternatives']={section:render('foot',p,foot_section=section) for section in ('colors-dark','colors')}
                result['limitations'].append({'target':'foot','status':'format-check-after-dependencies','reason':'Choose [colors-dark] or legacy [colors] using installed Foot --check-config; colors and other user file edits stay as reviewed'})
                main=config/'foot/foot.ini';text=main.read_text() if main.exists() else ''
                # Include has its own section scope; a final [main] keeps it global.
                add(main,_block(text,'[main]\ninclude='+str(fragment)))
                if foot_shell not in ('bash','zsh'):
                    result['limitations'].append({'target':'foot','status':'next-launch-only','reason':'Select bash/zsh per-terminal live hook explicitly; no unrelated TTYs will be touched'})
                else:
                    rc=home/('.bashrc' if foot_shell=='bash' else '.zshrc')
                    rc_text=rc.read_text() if rc.exists() else ''
                    source_line='. '+shlex.quote(str(hook))
                    blocks=re.findall(r'(?ms)^'+re.escape(BEGIN)+r'\n(.*?)^'+re.escape(END)+r'\n?',rc_text)
                    if any(block.strip()!=source_line for block in blocks):
                        raise ValueError('User-edited Foot shell integration requires review')
                    body=_foot_hook_content(sys.executable,Path(__file__).resolve(),palette_path)
                    add(hook,body,managed=True);add(rc,_block(rc_text,source_line))
                    add(palette_path,json.dumps(p))
                    result['limitations'].append({'target':'foot','status':'new-shell-required-once','reason':'Existing Foot shells need to source the reviewed hook once; thereafter updates are live'})
            result['managed'][target]={'main':str(main),'fragment':str(fragment)}
        except (OSError,UnicodeError,ValueError) as error:
            result['conflicts'].append({'target':target,'reason':str(error)})
    return result


def resolve_foot_plan(plan, *, runner=subprocess.run, foot_binary=None):
    """Resolve only the reviewed equivalent Foot fragment format after dependencies.

    Foot 1.28 rejects legacy [colors]. Probe the actual installed parser, never
    assume a version threshold. Includes are absolute or ~/ per foot.ini(5),
    so a temporary main file retains other user include semantics unchanged.
    No proposed user file is written during this capability/full-config check.
    """
    if 'foot' not in plan['targets']:return plan
    if plan.get('foot_format_policy')!='auto':raise ValueError('Review Foot automatic format selection before registration')
    resolved=copy.deepcopy(plan);spec=resolved['managed']['foot']
    fragment=next(row for row in resolved['files'] if row['path']==spec['fragment'])
    main=next(row for row in resolved['files'] if row['path']==spec['main'])
    alternatives=resolved.get('foot_format_alternatives',{})
    if set(alternatives)!={'colors-dark','colors'}:raise ValueError('Missing reviewed Foot format alternatives')
    body=lambda text:re.sub(r'(?m)^\[(?:colors-dark|colors)\]$', '[ADWS-COLORS]', text)
    if any(body(text)!=body(fragment['content']) for text in alternatives.values()):raise ValueError('Foot alternatives differ beyond the reviewed section name')
    for row in resolved['files']:
        path=Path(row['path'])
        if str(path.resolve())!=row['resolved'] or (_digest(path.read_bytes()) if path.exists() else None)!=row['before']:
            raise ValueError('Configuration changed after palette review: '+str(path))
    binary=foot_binary or shutil.which('foot')
    if not binary:raise ValueError('Install Foot before resolving its reviewed palette integration')
    include='include='+spec['fragment']
    if main['content'].count(include)!=1:raise ValueError('Foot palette include must appear exactly once in the reviewed main config')
    checks=[];chosen=None
    with tempfile.TemporaryDirectory(prefix='adws-foot-check-') as directory:
        temp=Path(directory);test_fragment=temp/'palette.ini';test_main=temp/'foot.ini'
        test_main.write_text(main['content'].replace(include,'include='+str(test_fragment)))
        for section in ('colors-dark','colors'):
            test_fragment.write_text(alternatives[section])
            reply=runner([str(binary),'--check-config','--config',str(test_main)],capture_output=True,text=True,timeout=10,
                         env={**os.environ,'HOME':resolved['home'],'LC_ALL':'C'})
            checks.append({'section':section,'exit':reply.returncode,'detail':(reply.stderr or reply.stdout or '')[-4000:]})
            if reply.returncode==0:chosen=section;break
    if chosen is None:raise ValueError('Installed Foot rejected the reviewed complete configuration: '+json.dumps(checks,ensure_ascii=False))
    fragment['content']=alternatives[chosen];spec['section']=chosen
    resolved['foot_format_resolution']={'policy':'auto','section':chosen,'binary':str(binary),'checks':checks}
    resolved['limitations']=[row for row in resolved['limitations'] if row.get('status')!='format-check-after-dependencies']
    return resolved


def register(plan, backup_dir, *, runner=subprocess.run, foot_binary=None):
    if plan.get('schema_version')!=SCHEMA or plan['conflicts']:raise ValueError('Palette registration conflicts must be resolved first')
    registry_file=registry_path(plan['config_home'])
    def checked_registry():
        if 'registry_before' not in plan:raise ValueError('Review palette registration again before writing')
        raw,_=_registry_snapshot(registry_file)
        if (str(registry_file.resolve())!=plan['registry_resolved']
                or (_digest(raw) if raw is not None else None)!=plan['registry_before']):
            raise ValueError('Palette registration changed after review')
        return raw
    checked_registry()
    plan=resolve_foot_plan(plan,runner=runner,foot_binary=foot_binary)
    backup=Path(backup_dir);backup.mkdir(parents=True,exist_ok=False,mode=0o700)
    files={};manifest=[]
    for index,row in enumerate(plan['files']):
        path=Path(row['path']);resolved=path.resolve()
        old=resolved.read_bytes() if resolved.exists() else None
        if str(resolved)!=row['resolved'] or (_digest(old) if old is not None else None)!=row['before']:raise ValueError('Configuration changed after palette review: '+str(path))
        if old is not None:(backup/str(index)).write_bytes(old)
        manifest.append({'path':str(path),'resolved':str(path.resolve()),'backup':str(index),'existed':old is not None,'installed_sha256':_digest(row['content'].encode())})
        files[path]=row['content'].encode()
    registry={key:plan[key] for key in ('schema_version','config_home','data_home','home','targets','base_icon_theme','foot_shell','managed','limitations')}
    if 'foot_format_resolution' in plan:registry['foot_format_resolution']=plan['foot_format_resolution']
    old=checked_registry()
    index=len(manifest)
    if old is not None:(backup/str(index)).write_bytes(old)
    registry_content=(json.dumps(registry,ensure_ascii=False,indent=2)+'\n').encode()
    manifest.append({'path':str(registry_file),'resolved':str(registry_file.resolve()),'backup':str(index),'existed':old is not None,'installed_sha256':_digest(registry_content)})
    files[registry_file]=registry_content
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    from adws_atomic import replace_files
    replace_files(files)
    return {'status':'registered','backup':str(backup),'limitations':plan['limitations'],'foot_format_resolution':plan.get('foot_format_resolution')}


def rollback_registration(backup_dir):
    """Restore registration edits while keeping later user changes intact."""
    directory=Path(backup_dir);manifest=json.loads((directory/'manifest.json').read_text())
    restored=[];conflicts=[]
    from adws_atomic import replace_files
    for index,row in reversed(list(enumerate(manifest))):
        path=Path(row['path'])
        if str(path.resolve())!=row.get('resolved',str(path.resolve())):
            conflicts.append(str(path));continue
        if path.exists() and _digest(path.read_bytes())!=row['installed_sha256']:
            conflicts.append(str(path));continue
        if row['existed']:
            if not path.exists():conflicts.append(str(path));continue
            replace_files({path:(directory/str(index)).read_bytes()})
        else:path.unlink(missing_ok=True)
        restored.append(str(path))
    return {'status':'conflicts' if conflicts else 'restored','restored':restored,'conflicts':conflicts}


def _ini_theme(text, name):
    parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str
    if text:parser.read_string(text)
    if not parser.has_section('Settings'):parser.add_section('Settings')
    parser.set('Settings','gtk-icon-theme-name',name)
    import io
    out=io.StringIO();parser.write(out);return out.getvalue()


def icon_files(palette, data_home, theme, base):
    p=validate_palette(palette);folder=Path(data_home)/'icons'/theme
    index=f'{MARKER}\n[Icon Theme]\nName={theme}\nComment=ADWS generated default icon; other app icons inherit the selected theme\nInherits={base},hicolor\nDirectories=scalable/apps\n[scalable/apps]\nSize=48\nMinSize=16\nMaxSize=256\nType=Scalable\nContext=Applications\n'
    # Independently drawn generic application card, no third-party icon copies.
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><rect x="5" y="6" width="38" height="36" rx="8" fill="{p["primary"]}"/><path d="M5 17h38" stroke="{p["on_primary"]}" stroke-width="2"/><circle cx="11" cy="12" r="1.4" fill="{p["on_primary"]}"/><path d="m19 24-5 5 5 5m10-10 5 5-5 5" fill="none" stroke="{p["on_primary"]}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>\n'
    return {folder/'index.theme':index.encode(),folder/'scalable/apps/application-x-executable.svg':svg.encode()}


def _running(name, proc=Path('/proc')):
    found=[]
    for entry in proc.iterdir():
        if not entry.name.isdigit():continue
        try:
            if entry.stat().st_uid!=os.getuid():continue
            if (entry/'comm').read_text().strip()!=name:continue
            argv=(entry/'cmdline').read_bytes().decode().rstrip('\0').split('\0')
            if name=='kitty':
                env=dict(x.split('=',1) for x in (entry/'environ').read_bytes().decode().split('\0') if '=' in x)
                if env.get('KITTY_CONFIG_DIRECTORY'):argv += ['--config',str(Path(env['KITTY_CONFIG_DIRECTORY'])/'kitty.conf')]
            found.append((int(entry.name),argv))
        except (OSError,UnicodeError):continue
    return found


def _uses_config(argv, expected, flags):
    for index,arg in enumerate(argv):
        if arg in flags and index+1<len(argv) and Path(argv[index+1]).expanduser().resolve()!=Path(expected).resolve():return False
        if any(arg.startswith(flag+'=') for flag in flags) and Path(arg.split('=',1)[1]).expanduser().resolve()!=Path(expected).resolve():return False
    return True


def refresh(target, registration, runner=subprocess.run, process_finder=_running, signaler=os.kill):
    managed=registration['managed'].get(target,{})
    if target=='kitty':
        processes=process_finder('kitty');sent=0;skipped=0
        for pid,argv in processes:
            if not _uses_config(argv,managed['main'],('--config','-c')):skipped+=1;continue
            signaler(pid,signal.SIGUSR1);sent+=1
        return {'status':'reload-requested' if sent else 'not-running','count':sent,'custom_config_skipped':skipped}
    if target=='alacritty':return {'status':'file-watch','mechanism':'Alacritty live_config_reload'}
    if target=='foot':
        if not registration.get('foot_shell'):return {'status':'next-launch-only'}
        watchers=foot_watchers(Path(registration['config_home'])/'adws/palette/foot.json')
        return {'status':'file-watch' if watchers else 'hook-activation-pending',
                'active_shells':len(watchers),'existing_shells':'Source the reviewed hook once in each existing Foot shell'}
    if target in ('mako','dunst'):
        processes=process_finder(target)
        if not processes:return {'status':'not-running'}
        flags=('--config','-c') if target=='mako' else ('--config','-config','-conf')
        if any(not _uses_config(argv,managed['main'],flags) for _,argv in processes):return {'status':'manual','reason':'Notification daemon uses an unrelated custom configuration'}
        command=[target+'ctl','reload']
        runner(command,check=True,capture_output=True,text=True,timeout=5)
        return {'status':'reload-requested'}
    return {'status':'file-watch'}


def synchronize(palette, registry=None, *, config_home=None, runner=subprocess.run,
                process_finder=_running, signaler=os.kill):
    p=validate_palette(palette);config=Path(config_home or _config())
    if registry is None:
        path=registry_path(config)
        if not path.exists():return {'status':'not-registered','targets':{}}
        registry=json.loads(path.read_text())
    if registry.get('schema_version')!=SCHEMA:raise ValueError('Unsupported palette registration')
    if Path(registry['config_home']).resolve()!=config.resolve():raise ValueError('Palette configuration location changed')
    report={'status':'complete','targets':{},'palette_sha256':_digest(json.dumps(p,sort_keys=True).encode())};files={}
    from adws_atomic import replace_files
    for target in registry['targets']:
        if target not in TARGETS:raise ValueError('Unknown registered palette target')
        if target=='icons':continue
        try:
            spec=registry['managed'][target];main=Path(spec['main']);fragment=Path(spec['fragment'])
            if not fragment.read_text().startswith(MARKER):raise ValueError('Managed fragment was replaced by user content')
            if target in ('kitty','mako','foot') and str(fragment) not in main.read_text():raise ValueError('Palette include was removed; preserving current user configuration')
            if target=='alacritty':
                current=tomllib.loads(main.read_text())
                if str(fragment) not in current.get('general',{}).get('import',[]) or current.get('general',{}).get('live_config_reload') is False or 'colors' in current:
                    raise ValueError('Alacritty palette import/reload changed or inline user colors take precedence')
            files[fragment]=render(target,p,foot_section=spec.get('section')).encode() if target=='foot' else render(target,p).encode()
            if target=='foot' and registry.get('foot_shell'):files[config/'adws/palette/foot.json']=json.dumps(p).encode()
            report['targets'][target]={'status':'written'}
        except (OSError,ValueError,KeyError) as error:report['targets'][target]={'status':'failed','reason':str(error)}
    active_theme=None
    if 'icons' in registry['targets']:
        try:
            base=registry['base_icon_theme']
            if not isinstance(base,str) or not re.fullmatch(r'[\w .+-]+',base):raise ValueError('Invalid base icon theme')
            current=runner(['gsettings','get','org.gnome.desktop.interface','icon-theme'],check=True,capture_output=True,text=True,timeout=5).stdout.strip().strip("'")
            if current not in (base,'ADWS-Palette-A','ADWS-Palette-B'):raise ValueError('User selected another icon theme; automatic override stopped')
            active_theme='ADWS-Palette-B' if current=='ADWS-Palette-A' else 'ADWS-Palette-A'
            index=Path(registry['data_home'])/'icons'/active_theme/'index.theme'
            if index.exists() and not index.read_text().startswith(MARKER):raise ValueError('ADWS icon theme name collides with a user theme')
            generated=icon_files(p,registry['data_home'],active_theme,base)
            for version in ('gtk-3.0','gtk-4.0'):
                path=config/version/'settings.ini';text=path.read_text() if path.exists() else ''
                generated[path]=_ini_theme(text,active_theme).encode()
            files.update(generated)
            report['targets']['icons']={'status':'written','theme':active_theme}
        except (OSError,ValueError,subprocess.SubprocessError,configparser.Error) as error:
            active_theme=None
            report['targets']['icons']={'status':'failed','reason':str(error)}
    if files:replace_files(files)
    if active_theme is not None:
        try:
            runner(['gsettings','set','org.gnome.desktop.interface','icon-theme',active_theme],check=True,capture_output=True,text=True,timeout=5)
            report['targets']['icons']['status']='theme-notified'
        except (OSError,subprocess.SubprocessError) as error:report['targets']['icons']={'status':'failed','reason':str(error)}
    for target,result in list(report['targets'].items()):
        if target=='icons' or result['status']!='written':continue
        try:report['targets'][target]=refresh(target,registry,runner,process_finder,signaler)
        except (OSError,subprocess.SubprocessError) as error:report['targets'][target]={'status':'failed','reason':str(error)}
    if any(v['status'] in ('failed','manual','next-launch-only','hook-activation-pending') for v in report['targets'].values()):report['status']='partial'
    state=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/palette-last-result.json'
    replace_files({state:(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()})
    return report


def foot_sequences(palette):
    p=validate_palette(palette)
    return ''.join(f'\x1b]{code};{p[role]}\x1b\\' for code,role in ((10,'on_surface'),(11,'surface'),(12,'primary'),(17,'primary'),(19,'on_primary'))).encode('ascii')


def _foot_runtime():
    value=os.environ.get('XDG_RUNTIME_DIR')
    if not value:return None
    root=Path(value)
    if not root.is_dir() or root.stat().st_uid!=os.getuid():return None
    return root/'adws/palette-foot'


def foot_watchers(palette_path):
    root=_foot_runtime()
    if root is None or not root.exists():return []
    result=[]
    for record in root.glob('*.json'):
        try:
            if record.stat().st_uid!=os.getuid() or record.stat().st_size>4096:continue
            data=json.loads(record.read_text());pid=data.get('pid')
            if type(pid) is not int or pid<=1 or data.get('palette')!=str(Path(palette_path).resolve()):continue
            process=Path('/proc')/str(pid)
            if process.stat().st_uid!=os.getuid():continue
            args=(process/'cmdline').read_bytes().decode().split('\0')
            if str(Path(__file__).resolve()) not in args or '--watch-foot' not in args:continue
            result.append(pid)
        except (OSError,ValueError,UnicodeError):continue
    return result


def watch_foot(path, parent, *, tty_fd=None, once=False):
    """Explicit per-shell helper, writes only its own controlling terminal FD."""
    if type(parent) is not int or parent<=1:raise ValueError('Invalid parent shell PID')
    if not os.environ.get('TERM','').startswith('foot'):raise ValueError('Foot hook must run inside a Foot terminal')
    opened=tty_fd is None
    fd=os.open('/dev/tty',os.O_WRONLY|os.O_NOCTTY|os.O_NONBLOCK) if opened else tty_fd
    registration=None;handlers={}
    try:
        info=os.fstat(fd)
        # /dev/tty is the kernel's own controlling-terminal multiplexer. Its
        # device node belongs to root, not the terminal user. Injected test FDs
        # still require ownership; production never searches another tty path.
        if not stat.S_ISCHR(info.st_mode) or (not opened and info.st_uid!=os.getuid()) or not os.isatty(fd):raise ValueError('Foot helper requires its own user terminal')
        if not once and threading.current_thread() is threading.main_thread():
            def stop(_signum,_frame):raise SystemExit(0)
            for number in (signal.SIGHUP,signal.SIGTERM):
                handlers[number]=signal.signal(number,stop)
        runtime=_foot_runtime()
        if runtime is not None and not once:
            runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
            registration=runtime/(str(os.getpid())+'.json')
            registration.write_text(json.dumps({'pid':os.getpid(),'parent':parent,'palette':str(Path(path).resolve())}))
        previous=None
        while True:
            try:os.kill(parent,0)
            except ProcessLookupError:return
            try:
                with Path(path).open('rb') as stream:data=stream.read(16385)
                if len(data)>16384:raise ValueError('Invalid Foot palette size')
                if data!=previous:
                    os.write(fd,foot_sequences(json.loads(data)));previous=data
            except (OSError,ValueError):
                if once:raise
            if once:return
            time.sleep(1)
    finally:
        if registration is not None:registration.unlink(missing_ok=True)
        for number,handler in handlers.items():signal.signal(number,handler)
        if opened:os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--watch-foot');parser.add_argument('--parent',type=int)
    args=parser.parse_args(argv)
    if not args.watch_foot or args.parent is None:parser.error('A Foot palette path and parent shell are required')
    watch_foot(args.watch_foot,args.parent)
    return 0

if __name__=='__main__':raise SystemExit(main())

"""Reviewed Niri session input environment and user service enablement.

No global input environment or audio-server replacement. Service enablement is
for the next login, never --now/restart. Callers must snapshot snapshot_targets
before apply and add include_line to the Niri configuration they validate.

References:
https://fcitx-im.org/wiki/Using_Fcitx_5_on_Wayland
https://github.com/niri-wm/niri/wiki/Configuration:-Miscellaneous
https://pipewire.pages.freedesktop.org/wireplumber/daemon/running.html
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

SCHEMA = 1
INPUT_VARIABLES = ('GTK_IM_MODULE','QT_IM_MODULE','QT_IM_MODULES','XMODIFIERS')
UNITS = ('pipewire.socket','pipewire-pulse.socket','pulseaudio.socket',
         'wireplumber.service','pipewire-media-session.service')
SESSION_HEADER = '// ADWS Niri session input environment; do not source in login shells.\n'
SESSION_HASH = '// ADWS session content-sha256: '
FCITX_ENVIRONMENT = {'XMODIFIERS':'@im=fcitx','QT_IM_MODULE':'fcitx','QT_IM_MODULES':'wayland;fcitx'}


def environment_text(environment, *, stamped=True):
    text = SESSION_HEADER
    if environment:
        text += 'environment {\n'+''.join('    '+key+' '+json.dumps(value)+'\n' for key,value in environment.items())+'}\n'
    return (SESSION_HASH+hashlib.sha256(text.encode()).hexdigest()+'\n'+text) if stamped else text


def managed_environment_unchanged(path):
    """Accept our exact legacy templates or a valid newer ownership checksum.

    The ordinary pre-apply file hash only detects edits after planning. This
    check detects personal edits made since an earlier install as well.
    """
    if not path.exists(): return not path.is_symlink()
    text = path.read_text()
    if text.startswith(SESSION_HASH):
        header, _, body = text.partition('\n')
        return header == SESSION_HASH+hashlib.sha256(body.encode()).hexdigest() and body.startswith(SESSION_HEADER)
    return text in (environment_text({}, stamped=False), environment_text(FCITX_ENVIRONMENT, stamped=False))


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def unit_states(config_home, unit_dirs=None):
    """Inspect installed user unit files without requiring a running user bus."""
    config = Path(config_home)
    folders = [Path(p) for p in (unit_dirs or (config/'systemd/user',
        Path.home()/'.local/share/systemd/user', '/etc/systemd/user', '/usr/lib/systemd/user', '/lib/systemd/user'))]
    result = {}
    for name in UNITS:
        definition = next((folder/name for folder in folders if (folder/name).exists() or (folder/name).is_symlink()),None)
        if definition is None: result[name] = 'unavailable'; continue
        if definition.is_symlink() and definition.resolve() == Path('/dev/null'):
            result[name] = 'masked'; continue
        enabled = any(any(path.is_symlink() and path.exists() for path in folder.glob('*.wants/'+name))
                      or any(path.is_symlink() and path.exists() for path in folder.glob('*.requires/'+name)) for folder in folders)
        result[name] = 'enabled' if enabled else 'disabled'
    return result


def _statements(block):
    parts, start, index, quote = [], 0, 0, False
    while index < len(block):
        ch = block[index]
        if quote:
            if ch == "\\": index += 2; continue
            if ch == '"': quote = False
        elif ch == '"': quote = True
        elif block.startswith('//', index):
            parts.append(block[start:index])
            end = block.find('\n',index)
            if end < 0: return parts
            start = index = end+1
            continue
        elif ch in '\n;': parts.append(block[start:index]); start = index+1
        index += 1
    if quote: raise ValueError('Unterminated environment string')
    parts.append(block[start:])
    return parts


def niri_environment(path, exclude=None):
    """Conservative scanner: only simple standard KDL environment/include syntax.

    Unparsed input-related blocks are review items, never silently replaced.
    """
    values, unknown, visited, hashes = {}, [], set(), {}
    def read(current, required=False):
        current = Path(current).expanduser().resolve()
        if current in visited or (exclude and current == Path(exclude).resolve()): return
        if len(visited) >= 64: unknown.append(str(current)+': include limit'); return
        visited.add(current)
        if not current.exists():
            if required:unknown.append(str(current)+': required include missing')
            return
        hashes[str(current)] = _digest(current)
        text = current.read_text()
        # Block comments/disabled nodes containing env keys need proper parser
        # review rather than an unsafe attempt to infer whether they are active.
        if ('/*' in text or '/-' in text) and any(v in text for v in INPUT_VARIABLES):
            unknown.append(str(current)+': commented input environment requires review'); return
        clean = re.sub(r'(?m)^\s*//.*$', '', text)
        for line in clean.splitlines():
            if not re.match(r'^include\s+',line.strip()):continue
            try:
                from adws_install_kdl import include
                name,optional=include(line);child=Path(name).expanduser()
                read(child if child.is_absolute() else current.parent/child,required=not optional)
            except ValueError:unknown.append(str(current)+': unparsed include')
        for block in re.finditer(r'\benvironment\s*\{([^{}]*)\}',clean,re.S):
            try: statements = _statements(block.group(1))
            except ValueError:
                unknown.append(str(current)+': unparsed environment'); continue
            for raw in statements:
                raw = raw.strip()
                if not raw or raw.startswith('//'): continue
                try: args = shlex.split(raw,comments=False)
                except ValueError: unknown.append(str(current)+': unparsed environment'); continue
                if len(args) >= 2 and args[0] in INPUT_VARIABLES:
                    if len(args)>2 and args[2] != '//':
                        unknown.append(str(current)+': unparsed '+args[0]); continue
                    values[args[0]] = None if args[1] == 'null' else args[1]
    if path: read(path)
    return values, unknown, hashes


def plan(config_home, features, niri_path=None, environ=None, which=None, units=None):
    """Plan before dependencies are installed; apply rechecks their availability.

    features is feature_plan(...), not the entire workflow plan.
    """
    config = Path(config_home).expanduser().absolute()
    env_file = config/'adws/niri-session.kdl'
    which = which or shutil.which
    environ = dict(os.environ if environ is None else environ)
    units = unit_states(config) if units is None else dict(units)
    rows = {row['id']:row for row in features['features']}
    provider = rows.get('input',{}).get('provider') or ('fcitx5' if 'input' in rows else None)
    existing, unknown, source_hashes = niri_environment(niri_path,exclude=env_file)
    conflicts = [{'kind':'unparsed-environment','detail':item} for item in unknown]
    if not managed_environment_unchanged(env_file):
        conflicts.append({'kind':'modified-managed-session','path':str(env_file),
                          'detail':'Existing session settings were edited or are not ADWS-owned; preserve and review before regeneration.'})
    environment = {}
    if provider == 'fcitx5':
        environment = dict(FCITX_ENVIRONMENT)
        for key,value in environment.items():
            actual = existing[key] if key in existing else environ.get(key)
            if (key in existing and existing[key] is None) or actual not in (None,'',value):
                conflicts.append({'kind':'input-environment','key':key,'existing':actual,'requested':value})
        gtk = existing.get('GTK_IM_MODULE',environ.get('GTK_IM_MODULE'))
        if gtk not in (None,'','wayland'):
            conflicts.append({'kind':'gtk-wayland-override','key':'GTK_IM_MODULE','existing':gtk,
                              'detail':'Preserved; global GTK override bypasses native Wayland text input.'})
    commands = {}; required = []
    if provider:
        args = ['ibus-daemon','--daemonize','--xim'] if provider == 'ibus-daemon' else [provider]
        commands['input-method'] = args; required.append(provider)
    if 'notifications' in rows:
        command = rows['notifications'].get('provider') or 'mako'
        commands['notifications'] = [command]; required.append(command)
    if 'clipboard' in rows:
        for kind in ('text','image'): commands['clipboard-'+kind] = ['wl-paste','--type',kind,'--watch','cliphist','store']
        required += ['wl-paste','wl-copy','cliphist']
    session_prefix = ['env', *[key+'='+value for key,value in environment.items()]] if environment else []
    commands = {key:session_prefix+argv for key,argv in commands.items()}
    lock = [rows['lock'].get('provider') or 'swaylock'] if 'lock' in rows else None
    if lock: required += lock
    actions = []; audio_provider = None
    if 'audio' in rows:
        pulse = bool(which('pulseaudio')) or units.get('pulseaudio.socket') in ('enabled','enabled-runtime')
        pipepulse = units.get('pipewire-pulse.socket') in ('enabled','enabled-runtime')
        if pulse and pipepulse:
            conflicts.append({'kind':'audio-providers','detail':'PulseAudio and PipeWire Pulse both enabled/installed; preserve and review.'})
        audio_provider = 'pulseaudio' if pulse else 'pipewire-pulse'
        actions.append('pulseaudio.socket' if pulse else 'pipewire-pulse.socket')
    if 'preview' in rows or audio_provider == 'pipewire-pulse':
        actions.insert(0,'pipewire.socket')
        media = bool(which('pipewire-media-session')) or units.get('pipewire-media-session.service')=='enabled'
        wire = units.get('wireplumber.service')=='enabled'
        if media and wire:
            conflicts.append({'kind':'pipewire-session-managers','detail':'Both PipeWire session managers present; review existing ownership.'})
        actions.append('pipewire-media-session.service' if media else 'wireplumber.service')
    profile_writes = []; required_data = []
    locale = environ.get('LC_ALL') or environ.get('LC_MESSAGES') or environ.get('LANG','')
    profile = config/'fcitx5/profile'
    if features.get('mode') == 'fresh' and provider == 'fcitx5' and locale.lower().startswith('zh') and not (profile.exists() or profile.is_symlink()):
        profile_writes.append({'path':str(profile),'before_sha256':None,'content':
            '[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=pinyin\n\n'
            '[Groups/0/Items/0]\nName=keyboard-us\n\n[Groups/0/Items/1]\nName=pinyin\n\n[GroupOrder]\n0=Default\n'})
        data_dirs = [Path(environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')]
        data_dirs += [Path(value) for value in (environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share').split(':') if value]
        required_data.append([str(folder/'fcitx5/inputmethod/pinyin.conf') for folder in data_dirs])
    services = []
    for unit in dict.fromkeys(actions):
        state = units.get(unit,'unavailable')
        if state == 'masked': conflicts.append({'kind':'masked-service','unit':unit})
        services.append({'unit':unit,'before':state,'action':'preserve' if state=='enabled' else 'enable'})
    text = environment_text(environment)
    return {'schema_version':SCHEMA,'config_home':str(config),'niri_path':str(niri_path) if niri_path else None,
            'env_file':str(env_file),'env_kdl':text,'before_sha256':_digest(env_file),'environment':environment,
            'source_hashes':source_hashes,'include_line':'include '+json.dumps(str(env_file)),
            'input_provider':provider,'audio_provider':audio_provider,'startup_commands':commands,
            'session_argv_prefix':session_prefix,
            'lock_argv':lock,'required_commands':list(dict.fromkeys(required)), 'service_actions':services,
            'profile_writes':profile_writes,'required_data':required_data,
            'snapshot_targets':[str(env_file),str(config/'systemd/user')]+[row['path'] for row in profile_writes], 'conflicts':conflicts,
            'activation':'next_login',
            'limitations':['Existing systemd-launched apps need these variables explicitly; Niri environment is not global.',
                           'XWayland GTK applications may require per-app GTK_IM_MODULE=fcitx; native GTK is left on text-input-v3.']}


def apply(proposal, backup_dir, validate, run=None, which=None, units=None):
    """Apply reviewed files and enable units, never start/replace a live service.

    Caller owns the enclosing transaction snapshot (including systemd/user).
    validate(path) must validate the generated KDL fragment. The main Niri config
    containing include_line must be validated separately before commit.
    """
    run = run or subprocess.run; which = which or shutil.which
    if proposal.get('schema_version') != SCHEMA: raise ValueError('Unsupported session plan')
    if proposal['conflicts']: raise ValueError('Session configuration conflicts require review')
    path = Path(proposal['env_file'])
    if _digest(path) != proposal['before_sha256']: raise ValueError('Session environment changed after review')
    for name,digest in proposal['source_hashes'].items():
        if _digest(Path(name)) != digest: raise ValueError('Niri input environment changed after review: '+name)
    missing = [name for name in proposal['required_commands'] if not which(name)]
    if missing: raise RuntimeError('Session commands are not installed: '+', '.join(missing))
    for candidates in proposal.get('required_data',[]):
        if not any(Path(name).is_file() for name in candidates):
            raise RuntimeError('Pinyin input method data is not installed')
    for row in proposal.get('profile_writes',[]):
        if _digest(Path(row['path'])) != row['before_sha256'] or Path(row['path']).is_symlink():
            raise ValueError('Input profile changed after review')
    current = unit_states(proposal['config_home']) if units is None else units
    for action in proposal['service_actions']:
        if current.get(action['unit']) not in ('enabled','disabled'):
            raise RuntimeError('User service is unavailable or masked: '+action['unit'])
    if proposal['audio_provider'] == 'pipewire-pulse' and (which('pulseaudio') or current.get('pulseaudio.socket') == 'enabled'):
        raise RuntimeError('PulseAudio appeared after review; refusing to replace it')
    chosen = {action['unit'] for action in proposal['service_actions']}
    opposites = [('pulseaudio.socket','pipewire-pulse.socket'),('wireplumber.service','pipewire-media-session.service')]
    for left,right in opposites:
        if (left in chosen and current.get(right)=='enabled') or (right in chosen and current.get(left)=='enabled'):
            raise RuntimeError('Competing service ownership changed after review')
    backup = Path(backup_dir); backup.mkdir(parents=True,exist_ok=False)
    if path.exists(): shutil.copy2(path,backup/'niri-session.kdl')
    (backup/'plan.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary = tempfile.mkstemp(prefix='.adws-session-',suffix='.kdl',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as file: file.write(proposal['env_kdl']);file.flush();os.fsync(file.fileno())
        validate(Path(temporary))
        if _digest(path) != proposal['before_sha256']: raise ValueError('Session environment changed during validation')
        os.chmod(temporary,path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary,path)
    finally: Path(temporary).unlink(missing_ok=True)
    for row in proposal.get('profile_writes',[]):
        target = Path(row['path']);target.parent.mkdir(parents=True,exist_ok=True)
        # New profile only: never truncate one created concurrently by Fcitx.
        with target.open('x',encoding='utf-8') as stream:stream.write(row['content'])
    for action in proposal['service_actions']:
        if current[action['unit']]=='enabled': continue
        run(['systemctl','--user','--no-reload','enable',action['unit']],check=True,timeout=15,
            env={**os.environ,'XDG_CONFIG_HOME':proposal['config_home']})
    after = unit_states(proposal['config_home']) if units is None else units
    if any(after.get(action['unit']) != 'enabled' for action in proposal['service_actions']):
        raise RuntimeError('User service enablement did not persist; configuration must be rolled back')
    return {'status':'configured','backup':str(backup),'activation':'next_login',
            'include_line':proposal['include_line'],'services':proposal['service_actions']}

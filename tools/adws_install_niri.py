"""Plan and validate portable Niri defaults without replacing personal settings.

Hardware configuration is deliberately omitted: Niri selects modes/scales for the
current outputs. Migration must run this generator on the destination, never copy
old output/GPU environment blocks. All executable bindings are checked locally.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
BEGIN = '// ==== ADWS installation rules BEGIN ===='
END = '// ==== ADWS installation rules END ===='
BLOCK = re.compile(r'(?ms)^' + re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?')
DEFAULT_HEADER = '// ADWS installation schema 1. Personal settings survive uninstall.'


def quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def command(argv):
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(arg, str) or '\0' in arg for arg in argv):
        raise ValueError('Commands must be nonempty argument lists, not shell strings')
    return ' '.join(map(quote, argv))


def available(argv, *, which=None):
    """Check the launched executable and explicit script, not just an env wrapper."""
    command(argv)
    which = which or shutil.which
    executable = argv[0]
    if '/' in executable:
        found = Path(executable).is_absolute() and Path(executable).is_file() and os.access(executable, os.X_OK)
    else:
        found = bool(which(executable))
    if not found: return False
    if Path(executable).name == 'env':
        args = list(argv[1:])
        while args and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=.*', args[0], re.S):
            # An altered search path cannot be checked using this process's PATH.
            if args[0].startswith('PATH='): return False
            args.pop(0)
        if args and args[0] == '--': args.pop(0)
        return bool(args) and not args[0].startswith('-') and available(args, which=which)
    if Path(executable).name in ('bash', 'sh', 'python', 'python3') and len(argv) > 1 and not argv[1].startswith('-'):
        return Path(argv[1]).is_absolute() and Path(argv[1]).is_file()
    return True


FEATURE_ACTIONS = {
    'lock': ('lock', 'Mod+Alt+L'),
    'clipboard': ('clipboard', 'Mod+Alt+V'),
    'volume_up': ('audio', 'XF86AudioRaiseVolume'),
    'volume_down': ('audio', 'XF86AudioLowerVolume'),
    'volume_mute': ('audio', 'XF86AudioMute'),
    'microphone_mute': ('audio', 'XF86AudioMicMute'),
    'brightness_up': ('brightness', 'XF86MonBrightnessUp'),
    'brightness_down': ('brightness', 'XF86MonBrightnessDown'),
    'wallpaper': ('wallpaper', 'Mod+Alt+W'),
}
NEUTRAL_BACKGROUND = '#242936'


def feature_ids(features):
    """Accept selected IDs or the shared feature-plan object, never infer taskbar extras."""
    if features is None: return set()
    if isinstance(features, dict): features = features.get('features', [])
    if isinstance(features, str): raise ValueError('Features must be an iterable of feature IDs')
    return {row['id'] if isinstance(row, dict) else row for row in features}


def action_commands(root, features, lock_argv=None, *, require_installed=True, which=None):
    """Build exact argv for a reviewed feature selection without opening hardware.

    Use require_installed=False for the pre-install plan. Regenerate with True
    after package installation and pass commands + selected features to plan().
    Missing tools are reported, never emitted as dead shortcuts. Brightness uses
    the existing coalescing worker, including its DDC throttling.
    """
    root = Path(root).resolve(); selected = feature_ids(features)
    which = which or shutil.which
    controls = str(root / 'tools/adws_quick_controls.py')
    clipboard = str(root / 'tools/adws_clipboard.py')
    launcher = str(root / 'adws')
    candidates = {
        'lock': lock_argv,
        'clipboard': ['python3', clipboard],
        'volume_up': ['python3', controls, 'sound', '--step', '5'],
        'volume_down': ['python3', controls, 'sound', '--step', '-5'],
        'volume_mute': ['pactl', 'set-sink-mute', '@DEFAULT_SINK@', 'toggle'],
        'microphone_mute': ['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', 'toggle'],
        'brightness_up': ['python3', controls, 'brightness', '--step', '5'],
        'brightness_down': ['python3', controls, 'brightness', '--step', '-5'],
        'wallpaper': ['bash', launcher, 'config', '--tab', 'wallpaper'],
    }
    dependencies = {
        'clipboard': ('python3', 'cliphist', 'wl-copy', 'wl-paste'),
        'audio': ('python3', 'pactl'),
        # The selected brightness feature installs both tools. Do not probe the
        # displays here: permissions/devices are checked only on user adjustment.
        'brightness': ('python3', 'brightnessctl', 'ddcutil'),
        'wallpaper': ('bash', 'python3'),
    }
    files = {'clipboard': [clipboard], 'audio': [controls], 'brightness': [controls],
             'wallpaper': [launcher, str(root / 'tools/adws-config.py')]}
    result = {'commands': {}, 'skipped': [], 'required_commands': [], 'required_files': [],
              'wallpaper_background': ({'color': NEUTRAL_BACKGROUND, 'scope': 'new-config-only',
                 'policy': 'native Niri fallback; existing wallpaper providers and images are preserved'}
                 if 'wallpaper' in selected else None)}
    for name, (feature, _) in FEATURE_ACTIONS.items():
        if feature not in selected: continue
        argv = candidates[name]
        if not argv:
            result['skipped'].append({'item': name, 'reason': 'selected-command-not-provided'}); continue
        command(argv)
        required = list(dependencies.get(feature, (argv[0],)))
        paths = files.get(feature, [])
        result['required_commands'].extend(required); result['required_files'].extend(paths)
        missing = [item for item in required if not which(item)] + [item for item in paths if not Path(item).is_file()]
        if require_installed and (missing or not available(argv, which=which)):
            result['skipped'].append({'item': name, 'reason': 'selected-program-not-installed', 'missing': missing})
        else:
            result['commands'][name] = list(argv)
    result['required_commands'] = list(dict.fromkeys(result['required_commands']))
    result['required_files'] = list(dict.fromkeys(result['required_files']))
    return result


def validate(binary, text, *, directory=None):
    """Validate only; never connect to or restart a running compositor."""
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.adws-validate-', suffix='.kdl', dir=directory) as stream:
            stream.write(text); stream.flush()
            result = subprocess.run([str(binary), 'validate', '-c', stream.name], capture_output=True, text=True, timeout=10)
        return result.returncode == 0, (result.stderr or result.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)


def capabilities(binary):
    result = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError('Cannot run selected Niri: ' + (result.stderr or result.stdout).strip())
    version = result.stdout.strip()
    # A version string is provenance information, not a capability promise.
    flavor = 'fork' if re.search(r'shorin|adws|maomaowm', version, re.I) else ('official-version-label' if re.fullmatch(r'niri \d+\.\d+(?:\.\d+)?', version) else 'unverified-build')
    with tempfile.TemporaryDirectory(prefix='adws-niri-capabilities-') as directory:
        include = Path(directory) / 'included.kdl'; include.write_text('// include probe\n')
        probes = {
            'include': 'include ' + quote(include) + '\n',
            'floating_rules': 'window-rule { match app-id="^adws-config$"; open-floating true; }\n',
            'modifier_tap': 'binds { Mod { spawn "true"; }; }\n',
            'modifier_release': 'binds { Mod { release { spawn "true"; }; }; }\n',
            'overview': 'binds { Mod+Tab { toggle-overview; }; }\n',
        }
        supported = {name: validate(binary, text)[0] for name, text in probes.items()}
    return {'version': version, 'flavor': flavor, 'capabilities': supported}


# Reference: the effective local keyboard configuration on 2026-11-06. These
# are independently generated native actions, not imported personal scripts.
# Mod+A/D move between columns; Mod+H/L focus columns. Do not reuse either for
# launching apps or locking. See docs/installer-keybindings.md for the map.
DIRECTIONS = (('left', 'Left', 'H', 'A'), ('down', 'Down', 'J', 'S'),
              ('up', 'Up', 'K', 'W'), ('right', 'Right', 'L', 'D'))
ACTIONS = [
    ('Mod+Q', 'close-window;'),
    ('Mod+MouseMiddle', 'close-window;'),
    *[(f'Mod+{key}', f'focus-{"column" if direction in ("left", "right") else "window"}-{direction};')
      for direction, arrow, vim, _ in DIRECTIONS for key in (arrow, vim)],
    ('Mod+A', 'consume-or-expel-window-left;'), ('Mod+D', 'consume-or-expel-window-right;'),
    ('Mod+W', 'focus-window-up;'), ('Mod+S', 'focus-window-down;'),
    *[(f'Mod+Ctrl+{key}', f'move-{"column" if direction in ("left", "right") else "window"}-{direction};')
      for direction, arrow, vim, wasd in DIRECTIONS for key in (arrow, vim, wasd)],
    *[(f'Mod+Shift+{key}', f'focus-monitor-{direction};')
      for direction, arrow, vim, _ in DIRECTIONS for key in (arrow, vim)],
    *[(f'Mod+Ctrl+Shift+{key}', f'move-column-to-monitor-{direction};')
      for direction, arrow, vim, wasd in DIRECTIONS for key in (arrow, vim, wasd)],
    *[(f'Mod+Alt+Shift+{key}', f'move-workspace-to-monitor-{direction};')
      for direction, arrow, vim, wasd in DIRECTIONS for key in (arrow, vim, wasd)],
    *[(f'Mod+{key}', f'focus-workspace-{direction};')
      for direction, keys in (('up', ('Page_Up', 'I')), ('down', ('Page_Down', 'U'))) for key in keys],
    *[(f'Mod+Ctrl+{key}', f'move-column-to-workspace-{direction};')
      for direction, keys in (('up', ('Page_Up', 'I')), ('down', ('Page_Down', 'U'))) for key in keys],
    ('Mod+Home', 'focus-column-first;'), ('Mod+End', 'focus-column-last;'),
    ('Mod+Ctrl+Home', 'move-column-to-first;'), ('Mod+Ctrl+End', 'move-column-to-last;'),
    ('Mod+BracketLeft', 'consume-or-expel-window-left;'), ('Mod+BracketRight', 'consume-or-expel-window-right;'),
    ('Mod+Comma', 'consume-window-into-column;'), ('Mod+Period', 'expel-window-from-column;'),
    ('Mod+Shift+A', 'consume-window-into-column;'), ('Mod+Shift+D', 'expel-window-from-column;'),
    ('Mod+X', 'toggle-column-tabbed-display;'), ('Mod+Shift+X', 'toggle-column-tabbed-display;'),
    ('Mod+MouseForward', 'focus-window-up;'), ('Mod+MouseBack', 'focus-window-down;'),
    ('Mod+F', 'maximize-column;'), ('Mod+Alt+F', 'fullscreen-window;'),
    ('Mod+M', 'minimize-window;'), ('Mod+Ctrl+F', 'expand-column-to-available-width;'),
    ('Mod+V', 'toggle-window-floating;'), ('Mod+Shift+V', 'switch-focus-between-floating-and-tiling;'),
    ('Mod+N', 'switch-focus-between-floating-and-tiling;'), ('Mod+Alt+N', 'switch-focus-between-floating-and-tiling;'),
    ('Alt+grave', 'switch-focus-between-floating-and-tiling;'),
    ('Mod+R', 'switch-preset-column-width;'), ('Mod+C', 'center-column;'),
    ('Mod+Shift+R', 'switch-preset-window-height;'), ('Mod+Ctrl+R', 'reset-window-height;'),
    ('Mod+Ctrl+C', 'center-visible-columns;'),
    ('Mod+Minus', 'set-column-width "-5%";'), ('Mod+Equal', 'set-column-width "+5%";'),
    ('Mod+Shift+Minus', 'set-window-height "-5%";'), ('Mod+Shift+Equal', 'set-window-height "+5%";'),
    ('Print', 'screenshot;'), ('Ctrl+Print', 'screenshot-window;'), ('Shift+Print', 'screenshot-screen;'),
    ('Mod+Alt+A', 'screenshot;'), ('Mod+Ctrl+Alt+A', 'screenshot-window;'),
    ('Mod+Ctrl+Alt+Shift+A', 'screenshot-screen;'),
    ('Mod+Shift+Slash', 'show-hotkey-overlay;'), ('Mod+Shift+E', 'quit;'),
    ('Mod+Escape', 'toggle-keyboard-shortcuts-inhibit;'),
    ('Mod+Alt+WheelScrollUp', 'adjust-magnifier-zoom 0.2;'),
    ('Mod+Alt+WheelScrollDown', 'adjust-magnifier-zoom -0.2;'),
    ('Mod+Shift+Z', 'toggle-magnifier;'),
    *[(key, 'toggle-overview;') for key in ('Mod+O', 'Mod+G', 'Mod+Alt+G')],
    ('Mod+WheelScrollDown', 'focus-column-right;'), ('Mod+WheelScrollUp', 'focus-column-left;'),
    ('Mod+Ctrl+WheelScrollDown', 'move-column-right;'), ('Mod+Ctrl+WheelScrollUp', 'move-column-left;'),
    ('Mod+Shift+WheelScrollDown', 'focus-workspace-down;'), ('Mod+Shift+WheelScrollUp', 'focus-workspace-up;'),
    ('Mod+Ctrl+Shift+WheelScrollDown', 'move-column-to-workspace-down;'),
    ('Mod+Ctrl+Shift+WheelScrollUp', 'move-column-to-workspace-up;'),
    *[(f'Mod+{n}', f'focus-workspace {n};') for n in range(1, 10)],
    *[(f'Mod+Ctrl+{n}', f'move-column-to-workspace {n};') for n in range(1, 10)],
]
RECENT_WINDOWS = [
    ('Mod+Tab', 'next-window scope="workspace";'),
    ('Mod+Shift+Tab', 'previous-window scope="workspace";'),
    ('Mod+grave', 'next-window filter="app-id";'),
    ('Mod+Shift+grave', 'previous-window filter="app-id";'),
    ('Alt+Tab', 'next-window;'), ('Alt+Shift+Tab', 'previous-window;'),
]
# No implicit dependency on the original machine's custom scripts, services,
# app IDs or force-kill helpers. Surface omissions rather than ship dead keys.
LOCAL_ONLY = {
    'quick-terminal': 'Mod+Slash',
    'force-kill-window': 'Alt+F4 / Alt+Shift+F4',
    'personal-bar-layouts': 'Mod+F2 / Mod+F3 / Mod+F4 / Mod+Shift+F4',
    'personal-snapshot-tools': 'Mod+F5 / Mod+F8',
    'translation-tools': 'Mod+F11 / Mod+Shift+T',
    'personal-color-selector': 'Mod+Alt+M / Mod+Alt+T',
    'random-wallpaper-tools': 'Mod+F10 / Mod+Shift+F10',
    'personal-app-focus': 'Mod+Ctrl+G / Mod+Shift+Q / Mod+Shift+O / Mod+Shift+W',
    'personal-power-menu': 'Mod+Shift+P',
}


def binding_identity(key):
    """Ignore modifier ordering and keysym casing, but keep Mod != Super.

    Niri maps Mod to Alt when nested, so treating it as an unconditional Super
    alias would incorrectly remove a valid binding. The full validator remains
    responsible for platform-specific key aliases.
    """
    parts = key.lower().split('+')
    aliases = {'control': 'ctrl'}
    return tuple(sorted(aliases.get(item, item) for item in parts[:-1])) + (parts[-1],)


def defaults(binary, root, applications, startup, report, actions=None, features=None):
    selected = feature_ids(features)
    background = ''
    if 'wallpaper' in selected:
        clause = 'background-color ' + quote(NEUTRAL_BACKGROUND) + ';'
        if validate(binary, 'layout { ' + clause + ' }\n')[0]:
            background = ' ' + clause
            report['wallpaper_background'] = {'color': NEUTRAL_BACKGROUND, 'status': 'native-fallback',
                'policy': 'drawn behind existing wallpaper; no new wallpaper process'}
        else:
            report['skipped'].append({'item': 'wallpaper-background', 'reason': 'unsupported-niri-background-color'})
    lines = [
        DEFAULT_HEADER,
        '// Output mode/scale and GPU environment are detected by Niri on this machine.',
        'input { keyboard { xkb {}; }; touchpad { tap; natural-scroll; }; }',
        'layout { gaps 8; default-column-width { proportion 0.5; };' + background + ' }',
        'cursor { xcursor-size 24; }',
    ]
    # Every binding is probed against the installed binary, including key names,
    # action properties and fork-only actions. Never guess based on the version.
    bindings = []
    seen = set()
    def remember(key, value):
        identity = binding_identity(key)
        if identity in seen:
            raise ValueError('Duplicate default Niri binding: ' + key)
        seen.add(identity)
        report['bindings'][key] = value
    for key, action in ACTIONS:
        prop = ' allow-inhibiting=false' if key == 'Mod+Escape' else ''
        if 'WheelScroll' in key and 'Shift+' in key: prop += ' cooldown-ms=150'
        if action in ('close-window;', 'toggle-overview;', 'quit;'): prop += ' repeat=false'
        entry = f'    {key}{prop} {{ {action} }}'
        if validate(binary, 'binds {\n' + entry + '\n}\n')[0]:
            remember(key, action); bindings.append(entry)
        else:
            report['skipped'].append({'item': key, 'reason': 'unsupported-niri-action'})
    # The current effective user profile leaves Ctrl taps empty. Super should
    # act only after a solo press/release; never substitute a press-time binding
    # on versions without this extension, which would break Super combinations.
    release = '    Super repeat=false { release { toggle-overview; }; }'
    if validate(binary, 'binds {\n' + release + '\n}\n')[0]:
        remember('Super', 'release { toggle-overview; };'); bindings.append(release)
    else:
        report['skipped'].append({'item': 'Super', 'reason': 'unsupported-modifier-release',
                                  'fallback': 'Mod+O / Mod+G'})
    recent = []
    for key, action in RECENT_WINDOWS:
        entry = f'    {key} {{ {action} }}'
        if validate(binary, 'recent-windows { binds {\n' + entry + '\n}; }\n')[0]:
            remember(key, action); recent.append(entry)
        else:
            report['skipped'].append({'item': key, 'reason': 'unsupported-native-window-switcher'})
    if recent:
        lines.append('recent-windows {\n  binds {\n' + '\n'.join(recent) + '\n  }\n}')
    chosen = dict(applications)
    if (root / 'adws').is_file():
        chosen.update(menu=['bash', str(root / 'adws'), 'start-menu'], settings=['bash', str(root / 'adws'), 'config'])
    # No portable shared-instance flag exists across terminals; both aliases
    # launch the selected terminal unchanged. Do not reserve the user's
    # screenshot-translation key (Mod+Shift+T) for a text editor.
    roles = {'terminal': ('Mod+Return', 'Mod+T'), 'browser': ('Mod+B',),
             'file_manager': ('Mod+E',), 'menu': ('Mod+Z',), 'settings': ('Mod+Alt+Comma',)}
    for role, keys in roles.items():
        argv = chosen.get(role)
        if argv and available(argv):
            for key in keys:
                entry = f'    {key} {{ spawn {command(argv)}; }}'
                if validate(binary, 'binds {\n' + entry + '\n}\n')[0]:
                    remember(key, list(argv)); bindings.append(entry)
                else:
                    report['skipped'].append({'item': key, 'reason': 'unsupported-niri-binding'})
        else:
            report['skipped'].append({'item': role, 'reason': 'selected-program-not-installed'})
    for name, (feature, key) in FEATURE_ACTIONS.items():
        if feature not in selected: continue
        argv = (actions or {}).get(name)
        if not argv or not available(argv):
            report['skipped'].append({'item': name, 'reason': 'selected-program-not-installed'}); continue
        # Holding lock/mute must not repeatedly spawn authentication prompts or
        # toggle sound on every keyboard repeat. Probe the property as well.
        prop = ' repeat=false' if name in ('lock', 'volume_mute', 'microphone_mute', 'clipboard', 'wallpaper') else ''
        if key.startswith('XF86'): prop += ' allow-when-locked=true'
        entry = f'    {key}{prop} {{ spawn {command(argv)}; }}'
        if validate(binary, 'binds {\n' + entry + '\n}\n')[0]:
            remember(key, list(argv)); bindings.append(entry)
        else:
            report['skipped'].append({'item': name, 'reason': 'unsupported-niri-binding'})
    for item, keys in LOCAL_ONLY.items():
        report['skipped'].append({'item': item, 'keys': keys, 'reason': 'personal-helper-not-part-of-portable-defaults'})
    for argv in startup:
        if available(argv):
            lines.append('spawn-at-startup ' + command(argv))
        else:
            report['conflicts'].append('Startup program is not installed: ' + command(argv))
    if report['capabilities']['floating_rules']:
        rules = (root / 'config/adws-windows.kdl').read_text()
        digest = hashlib.sha256(rules.encode()).hexdigest()
        lines.append(BEGIN + '\n// content-sha256: ' + digest + '\n' + rules + END)
    lines.append('binds {\n' + '\n'.join(bindings) + '\n}')
    return '\n'.join(lines) + '\n'


def relocation_plan(config_path, source_migration):
    """Review literal ADWS launch paths without regenerating personal keybindings.

    Only an ADWS-generated default configuration and known executable/script
    pairs are eligible. Shell strings and resources inside the old checkout are
    conflicts. Startup nodes are owned and reviewed by adws_install_startup.
    """
    from adws_install_startup import audit, relocation_evidence, literal_arguments
    path = Path(config_path).expanduser().absolute()
    result = {'schema_version':1,'config_path':str(path),'resolved_config_path':str(path.resolve()),'files':{},'originals':{},
              'source_hashes':{},'source_migration':None,'replacements':[],
              'snapshot_targets':[],'conflicts':[]}
    try: evidence = relocation_evidence(source_migration)
    except (OSError,ValueError,KeyError) as error:
        result['conflicts'].append(str(error));return result
    if not evidence or not path.is_file():return result
    result['source_migration']=evidence
    audited=audit(path.parent.parent,niri_path=path,enabled_units=[],autostart_dirs=[])
    result['audit']=audited
    if audited['unknown']:
        result['conflicts'].append('Niri include/startup syntax needs review before relocating commands');return result
    result['source_hashes']=dict(audited['source_hashes'])
    result['source_hashes'].update(evidence['source_hashes'])
    old_root=Path(evidence['previous_root']);new_root=Path(evidence['root'])
    generated=DEFAULT_HEADER in path.read_text().splitlines()
    pairs={('bash','adws'),('sh','adws'),('python3','tools/adws_clipboard.py'),
           ('python3','tools/adws_quick_controls.py')}
    def references(line):
        # Ignore comments, but decode literal strings before comparing paths so
        # escaped Unicode in an existing configuration is handled correctly.
        values=[];index=0
        while index<len(line):
            if line.startswith('//',index):break
            if line[index]=='"':
                try:value,end=json.JSONDecoder().raw_decode(line,index)
                except ValueError:return str(old_root) in line
                values.append(value);index=end
            else:index+=1
        return any(isinstance(value,str) and (value==str(old_root) or str(old_root)+'/' in value) for value in values)
    for name in audited['niri_files']:
        original=Path(name).read_text();lines=original.splitlines(keepends=True)
        # This older generated include carries its own exact binding template.
        from adws_vm_mode import toggle_binding
        key = re.search(r'^\s*([A-Za-z0-9+_-]+) repeat=false', original, re.M)
        header = '// Managed by ADWS virtual machine mode.\n'
        vm_script = Path('tools/adws_vm_mode.py')
        if (key and Path(name).name.startswith('.adws-vm-mode-')
                and original == header + toggle_binding(old_root / vm_script, key[1])
                and (new_root / vm_script).is_file()):
            result['originals'][name] = original
            result['files'][name] = header + toggle_binding(new_root / vm_script, key[1])
            result['replacements'].append({'path': name, 'line': 3,
                'before': [str(old_root / vm_script)], 'after': [str(new_root / vm_script)]})
            continue
        for number,line in enumerate(lines,1):
            if line.lstrip().startswith(('//','#','/-','spawn-at-startup ','spawn-sh-at-startup ')):continue
            if not references(line):continue
            # Retain the complete key expression, properties, spacing and
            # trailing comment. Replace just one decoded script-path token.
            match=re.match(r'^\s*[A-Za-z0-9_+.-]+(?:\s+[A-Za-z0-9_-]+=[^{}\n]+)?\s*\{\s*spawn\s+',line)
            reason=None
            if '/*' in original or '*/' in original:reason='Block comments around source references need review'
            elif not generated and DEFAULT_HEADER not in original.splitlines():reason='Configuration is not an ADWS-generated default'
            elif not match:reason='Old installation reference is not a supported literal binding'
            else:
                try:
                    argv,spans,end=literal_arguments(line,match.end())
                    suffix=line[end:]
                    if not re.fullmatch(r'\s*;\s*}\s*;?\s*(?://[^\n]*)?\n?',suffix):raise ValueError('Binding contains additional actions or shell syntax')
                    if len(argv)<2:raise ValueError('Binding has no explicit script')
                    script=Path(argv[1])
                    if not script.is_absolute() or not script.is_relative_to(old_root):raise ValueError('Old root is not the script argument')
                    relative=script.relative_to(old_root).as_posix()
                    if (argv[0],relative) not in pairs:raise ValueError('Executable/script pair is not an ADWS default entrypoint')
                    if any(str(old_root)+'/' in arg or arg==str(old_root) for i,arg in enumerate(argv) if i!=1):
                        raise ValueError('Additional old-source resource arguments need review')
                    target=new_root/relative
                    if not target.is_file():raise ValueError('New installation is missing the referenced script')
                    start,stop=spans[1]
                    lines[number-1]=line[:start]+quote(target)+line[stop:]
                    result['replacements'].append({'path':name,'line':number,'before':argv,'after':[argv[0],str(target),*argv[2:]]})
                except (ValueError,TypeError) as error:reason=str(error)
            if reason:result['conflicts'].append({'path':name,'line':number,'reason':reason})
        changed=''.join(lines)
        if changed!=original:
            result['files'][name]=changed;result['originals'][name]=original
    result['snapshot_targets']=list(result['files'])
    return result


def verify_relocation(proposal):
    from adws_install_startup import audit, verify_sources, relocation_evidence
    if proposal.get('schema_version')!=1 or proposal.get('conflicts'):
        raise ValueError('Niri source relocation requires review')
    verify_sources(proposal.get('source_hashes',{}))
    relocation_evidence(proposal.get('source_migration'))
    path=Path(proposal['config_path'])
    if str(path.resolve())!=proposal.get('resolved_config_path',str(path.resolve())):
        raise ValueError('Niri source relocation target changed after review')
    if proposal.get('audit'):
        current=audit(path.parent.parent,niri_path=path,enabled_units=[],autostart_dirs=[])
        if (current['unknown'] or current['niri_files']!=proposal['audit']['niri_files']
                or current['niri_includes']!=proposal['audit']['niri_includes']):
            raise ValueError('Niri include graph changed after relocation review')


def plan(mode, *, root=ROOT, config_path=None, applications=None, startup=None, binary=None, actions=None, features=None, relocation=None):
    """JSON-safe installation proposal; no user configuration is changed.

    Existing configs retain their shortcuts/startup/output settings. Only a
    validated, content-addressed include for ADWS window rules is proposed.
    Fresh/migrate without a target config creates portable complete defaults.
    """
    if mode not in ('fresh', 'integrate', 'migrate'):
        raise ValueError('Unknown installation mode')
    if set(actions or {}) - FEATURE_ACTIONS.keys(): raise ValueError('Unknown Niri feature action')
    from adws_windows import config_path as default_path
    from adws_niri_compat import niri_binary
    root = Path(root).resolve()
    path = Path(config_path) if config_path is not None else default_path()
    path = path.expanduser().absolute()
    binary = binary or niri_binary()
    result = {'schema': SCHEMA, 'mode': mode, 'config_path': str(path), 'binary': str(binary) if binary else None,
              'files': {}, 'originals': {}, 'conflicts': [], 'skipped': [], 'bindings': {}, 'validated': False,
              'hardware_policy': 'detect-on-target; never import source output/GPU blocks'}
    if not binary:
        result['conflicts'].append('Niri is not installed; install it and regenerate the plan before applying')
        return result
    result.update(capabilities(binary))
    if not validate(binary, '')[0]:
        result['conflicts'].append('Selected Niri cannot validate configurations; no files were generated')
        return result
    old = path.read_text() if path.is_file() else None
    if path.is_symlink() and not path.exists():
        result['conflicts'].append('Niri configuration is a dangling symlink: ' + str(path)); return result
    result['originals'][str(path)] = old
    if relocation:
        verify_relocation(relocation)
        if Path(relocation['config_path']).resolve()!=path.resolve():raise ValueError('Niri relocation belongs to another configuration')
        result['relocation']=relocation
        key=lambda name: str(path) if Path(name)==path.resolve() else name
        result['originals'].update({key(name):text for name,text in relocation['originals'].items()})
        result['files'].update({key(name):text for name,text in relocation['files'].items()})
        old=relocation['files'].get(str(path.resolve()),old)
    if old is not None:
        matches = list(BLOCK.finditer(old))
        if old.count(BEGIN) != len(matches) or old.count(END) != len(matches) or len(matches) > 1:
            result['conflicts'].append('Incomplete or duplicate managed Niri rule markers'); return result
        if matches:
            body = matches[0].group().splitlines()[1:-1]
            # A known managed include owns only itself, not arbitrary user KDL.
            if len(body) == 1 and (match := re.fullmatch(r'include "(\.adws-install-([0-9a-f]{20})\.kdl)"', body[0])):
                previous = path.parent / match[1]
                if not previous.is_file() or hashlib.sha256(previous.read_bytes()).hexdigest()[:20] != match[2]:
                    result['conflicts'].append('Managed Niri rule include was edited or removed; preserving user changes'); return result
            elif body and body[0].startswith('// content-sha256: '):
                payload = '\n'.join(body[1:]) + '\n'
                if hashlib.sha256(payload.encode()).hexdigest() != body[0].removeprefix('// content-sha256: '):
                    result['conflicts'].append('Managed Niri window rules were edited; preserving user changes'); return result
            else:
                result['conflicts'].append('Unknown content inside managed Niri markers; preserving user changes'); return result
        if not result['capabilities']['include']:
            result['conflicts'].append('This Niri does not support include; existing configuration was preserved'); return result
        if not result['capabilities']['floating_rules']:
            result['conflicts'].append('This Niri does not support ADWS floating settings rules'); return result
        rules = (root / 'config/adws-windows.kdl').read_text()
        digest = hashlib.sha256(rules.encode()).hexdigest()[:20]
        included = path.parent / ('.adws-install-' + digest + '.kdl')
        existing_include = included.read_text() if included.exists() else None
        if existing_include is not None and existing_include != rules:
            result['conflicts'].append('Managed Niri include has user changes: ' + str(included)); return result
        result['originals'][str(included)] = existing_include
        block = BEGIN + '\ninclude ' + quote(included.name) + '\n' + END + '\n'
        text = BLOCK.sub(lambda _: block, old) if matches else old.rstrip() + '\n\n' + block
        result['files'][str(included)] = rules
        result['files'][str(path)] = text
        # Keep original relative includes working; substitute only our new include
        # with a temporary absolute include while checking the uncommitted plan.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.kdl') as stream:
            stream.write(rules); stream.flush()
            check = text.replace('include ' + quote(included.name), 'include ' + quote(stream.name))
            if relocation and relocation.get('files'):
                from adws_install_startup import validate_candidates
                validation=[]
                def check_candidate(candidate):
                    validation.append(validate(binary,candidate.read_text(),directory=candidate.parent))
                candidates=dict(relocation['files']);candidates[str(path.resolve())]=check
                validate_candidates(relocation['audit'],candidates,check_candidate)
                ok,detail=validation[0]
            else:ok, detail = validate(binary, check, directory=path.parent)
    else:
        if mode == 'integrate':
            result['conflicts'].append('Integration requires an existing Niri configuration; choose fresh installation'); return result
        text = defaults(binary, root, applications or {}, startup or [], result, actions, features)
        result['files'][str(path)] = text
        ok, detail = validate(binary, text)
    result['validated'] = ok
    if not ok: result['conflicts'].append('Generated Niri configuration did not validate: ' + detail)
    return result


def apply(proposal, backup_dir):
    """Apply a reviewed proposal; abort on concurrent edits and retain a manifest."""
    if proposal.get('schema') != SCHEMA or not proposal.get('validated') or proposal.get('conflicts'):
        raise ValueError('Niri plan is not ready to apply')
    files = {Path(name): text for name, text in proposal['files'].items()}
    if proposal.get('relocation'): verify_relocation(proposal['relocation'])
    for name, old in proposal['originals'].items():
        path = Path(name)
        now = path.read_text() if path.is_file() else None
        if now != old or (old is None and path.is_symlink()):
            raise ValueError('Niri configuration changed after planning: ' + name)
    config = Path(proposal['config_path'])
    # Revalidate immediately before writing, including any unchanged user includes.
    text = files[config]
    with tempfile.TemporaryDirectory(prefix='adws-niri-apply-') as directory:
        relocated=set(proposal.get('relocation',{}).get('files',{}))
        for path, content in files.items():
            if path != config and str(path.resolve()) not in relocated:
                temp = Path(directory) / path.name; temp.write_text(content)
                text = text.replace('include ' + quote(path.name), 'include ' + quote(temp))
        relocation=proposal.get('relocation')
        if relocation and relocation.get('files'):
            from adws_install_startup import validate_candidates
            validation=[]
            def check_candidate(candidate):
                validation.append(validate(proposal['binary'],candidate.read_text(),directory=candidate.parent))
            candidates=dict(relocation['files']);candidates[str(config.resolve())]=text
            validate_candidates(relocation['audit'],candidates,check_candidate)
            ok,detail=validation[0]
        else:ok, detail = validate(proposal['binary'], text, directory=config.parent if config.parent.exists() else None)
    if not ok: raise ValueError('Niri validation failed before applying: ' + detail)
    if proposal.get('relocation'): verify_relocation(proposal['relocation'])
    backup = Path(backup_dir); backup.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, path in enumerate(files):
        target = backup / f'niri-{index}.kdl'
        existed = path.exists()
        if existed: shutil.copy2(path, target)
        manifest.append({'path': str(path), 'existed': existed, 'backup': str(target) if existed else None,
                         'installed_sha256': hashlib.sha256(files[path].encode()).hexdigest()})
    (backup / 'niri-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    from adws_atomic import replace_files
    replace_files({path: text.encode() for path, text in files.items()})
    return {'status': 'applied', 'backup': str(backup / 'niri-manifest.json'), 'config': str(config), 'requires_login': True}

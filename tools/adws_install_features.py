"""Shared, declarative Niri feature inventory for planning and acceptance.

Plans never install packages, change services, or open hardware. Package names are
candidates for the target distribution's repositories, not an availability claim.
The installer must resolve them before execution and must not report probes as
proof that a screenshot or a window preview has actually worked.
"""
import os
from pathlib import Path
import re
import shlex
import shutil

MANIFEST_VERSION = 1
MANAGERS = ('pacman', 'apt-get', 'dnf')


def packages(arch, debian=None, fedora=None):
    return dict(zip(MANAGERS, (arch.split(), (debian or arch).split(), (fedora or arch).split())))


THUNAR_PACKAGES = packages('thunar gvfs tumbler', fedora='Thunar gvfs tumbler')


FEATURE_MANIFEST = {
    'file-manager': {
        'label': '文件管理器、回收站与缩略图', 'commands': [('thunar',)],
        'packages': THUNAR_PACKAGES,
        'configs': ['inode/directory'],
        'services': ['GVfs and Tumbler (session D-Bus activation)'],
        'acceptance': ['directory association', 'open group folder', 'trash and thumbnails'],
    },
    'taskbar': {
        'label': '任务栏', 'commands': [('waybar',)],
        'packages': packages('waybar python-gobject python-cairo python-pillow gtk3 gtk-layer-shell polkit python-yaml',
            'waybar python3-gi python3-cairo python3-pil gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 gir1.2-polkit-1.0 policykit-1 python3-yaml',
            'waybar python3-gobject python3-cairo python3-pillow gtk3 gtk-layer-shell polkit python3-pyyaml'),
        'configs': ['waybar/config-bottom.jsonc', 'waybar/style-bottom.css', 'adws/taskbar-layout.json'],
        'services': ['ADWS taskbar (one session owner)'],
        'acceptance': ['Waybar compatibility', 'native library load', 'running taskbar on selected outputs'],
    },
    'preview': {
        'label': '窗口预览', 'commands': [('pipewire',), ('wireplumber', 'pipewire-media-session')],
        'packages': packages('pipewire gst-python gst-plugin-pipewire gst-plugins-base gst-plugins-good',
            'pipewire python3-gst-1.0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gstreamer1.0-pipewire gstreamer1.0-plugins-base gstreamer1.0-plugins-good',
            'pipewire python3-gstreamer1 pipewire-gstreamer gstreamer1-plugins-base gstreamer1-plugins-good'),
        'configs': [], 'services': ['pipewire.socket', 'existing PipeWire session manager'],
        'acceptance': ['Gst / GstApp and capture elements', 'real window capture produces a frame'],
    },
    'screenshot': {
        'label': '截图', 'commands': [('grim',), ('slurp',), ('wl-copy',)],
        'packages': packages('grim slurp wl-clipboard'), 'configs': ['Niri screenshot shortcuts'],
        'services': [], 'acceptance': ['capture a nonempty PNG in the active session'],
    },
    'clipboard': {
        'label': '剪贴板', 'commands': [('cliphist',), ('wl-copy',), ('wl-paste',)],
        'packages': packages('cliphist wl-clipboard'), 'configs': ['adws/clipboard-pins'],
        'services': ['single wl-paste --watch cliphist store owner'],
        'acceptance': ['clipboard round trip with existing contents preserved', 'history watcher running once'],
    },
    'input': {
        'label': '输入法', 'commands': [('fcitx5', 'ibus-daemon', 'fcitx')],
        'providers': ['fcitx5', 'ibus-daemon', 'fcitx'],
        'packages': packages('fcitx5 fcitx5-gtk fcitx5-qt fcitx5-chinese-addons',
            'fcitx5 fcitx5-frontend-gtk3 fcitx5-frontend-gtk4 fcitx5-frontend-qt5 fcitx5-frontend-qt6 fcitx5-chinese-addons',
            'fcitx5 fcitx5-gtk fcitx5-qt fcitx5-chinese-addons'),
        'configs': ['input method frontend environment (preserve existing provider)'],
        'services': ['one input method session owner; do not install fcitx5-autostart alongside ADWS owner'],
        'acceptance': ['provider D-Bus owner', 'Chinese input in ADWS and XWayland text fields'],
    },
    'audio': {
        'label': '音频', 'commands': [('pactl',)],
        'packages': packages('libpulse', 'pulseaudio-utils', 'pulseaudio-utils'),
        'configs': [], 'services': ['existing PulseAudio or PipeWire Pulse service'],
        'acceptance': ['pactl info', 'usable output devices or explicit no-device status'],
    },
    'brightness': {
        'label': '亮度', 'commands': [('brightnessctl', 'ddcutil')],
        'packages': packages('brightnessctl ddcutil'),
        'configs': ['ADWS merged brightness updates; preserve per-display settings'],
        'services': ['on-demand backlight/DDC access; no background hardware polling'],
        'acceptance': ['supported displays and permissions', 'one committed slider/scroll update without input stalls'],
    },
    'notifications': {
        'label': '通知', 'commands': [('notify-send',), ('mako', 'dunst', 'swaync')],
        'providers': ['mako', 'dunst', 'swaync'],
        'packages': packages('libnotify', 'libnotify-bin', 'libnotify'),
        'provider_packages': packages('mako', 'mako-notifier', 'mako'),
        'configs': ['notification provider configuration (preserve existing)'],
        'services': ['one org.freedesktop.Notifications owner'],
        'acceptance': ['notification D-Bus service', 'test notification displayed'],
    },
    'lock': {
        'label': '锁屏', 'commands': [('hyprlock', 'gtklock', 'swaylock', 'waylock')],
        'providers': ['hyprlock', 'gtklock', 'swaylock', 'waylock'],
        'packages': packages('swaylock'), 'configs': ['Niri lock shortcut'],
        'services': [], 'acceptance': ['locker executable and configuration', 'manual lock/unlock test'],
    },
    'wallpaper': {
        'label': '壁纸', 'commands': [('awww', 'swww', 'swaybg')],
        'providers': ['awww', 'swww', 'swaybg'],
        'packages': packages('swaybg'), 'configs': ['adws/wallpaper settings'],
        'services': ['one selected wallpaper engine'],
        'acceptance': ['wallpaper restored on selected outputs'],
    },
    'palette': {
        'label': '自动配色', 'commands': [('matugen',)],
        'packages': packages('matugen'), 'configs': ['matugen/config.toml', 'ADWS theme output paths'],
        'services': [], 'acceptance': ['Matugen template generation', 'taskbar/menu/icon/terminal/notification refresh'],
    },
}

# Keep separate records even when the feature list is the same: configuration
# ownership and migration differ; an existing installation is never a fresh one.
_ALL = tuple(FEATURE_MANIFEST)
_EXISTING = tuple(key for key in _ALL if key != 'file-manager')
MODE_MANIFESTS = {
    'fresh': {'features': _ALL, 'configuration': 'create-defaults', 'preserve_existing': True,
              'description': '全新安装：生成经校验的 Niri 默认配置；已有文件仍需备份与冲突检查。'},
    'integrate': {'features': _EXISTING, 'configuration': 'managed-include', 'preserve_existing': True,
                 'description': '已有 Niri 集成：保留现有快捷键、服务和显示设置，只添加 ADWS 管理部分。'},
    'migrate': {'features': _EXISTING, 'configuration': 'migrate-personal-only', 'preserve_existing': True,
               'description': '旧机迁移：迁移个人配置；显示与显卡配置在目标机重新生成。'},
}


def selected_features(mode, selected=None):
    if mode not in MODE_MANIFESTS:
        raise ValueError('Unknown installation mode: ' + str(mode))
    values = list(MODE_MANIFESTS[mode]['features'] if selected is None else selected)
    unknown = set(values) - FEATURE_MANIFEST.keys()
    if unknown:
        raise ValueError('Unknown installation features: ' + ', '.join(sorted(unknown)))
    return list(dict.fromkeys(values))


def _provider_command(argv):
    """Inspect literal launch wrappers without executing user configuration."""
    if not argv:return None
    name=Path(argv[0]).name
    if name=='env':
        args=list(argv[1:])
        while args and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=.*',args[0]):args.pop(0)
        if args[:1]==['--']:args.pop(0)
        return _provider_command(args)
    if name in ('sh','bash','zsh') and len(argv)==3 and argv[1] in ('-c','-lc'):
        try:args=shlex.split(argv[2])
        except ValueError:return None
        if any(re.search(r'[;&|<>`]|\$\(',arg) for arg in args):return None
        return _provider_command(args)
    if any(arg in ('&&','||',';','|','&') for arg in argv):return None
    return argv


def _provider_executable(argv):
    command=_provider_command(argv)
    return Path(command[0]).name if command else None


def provider_hints(config_home, niri_path=None, environ=None, audit_options=None):
    """Read configured owners/frontend environment before choosing dependencies.

    Installed binaries only supply a fallback when no owner/environment is
    configured. The caller must block on conflicts and recheck source_hashes
    before the first configuration mutation. No running service is changed.
    """
    from adws_install_startup import audit, components
    from adws_install_session_config import INPUT_VARIABLES, niri_environment
    def recognize(argv):
        found=components(argv)
        command=_provider_command(argv) or []
        executable=Path(command[0]).name if command else None
        if executable in ('awww-daemon','swww-daemon','swaybg') or (executable in ('awww','swww') and command[1:2]==['init']):
            found=found | {'wallpaper'}
        return found
    config=Path(config_home).expanduser().absolute()
    niri=Path(niri_path) if niri_path else config/'niri/config.kdl'
    audit_result=audit(config,niri_path=niri,recognizer=recognize,**(audit_options or {}))
    existing,unknown,env_hashes=niri_environment(niri)
    environment=dict(os.environ if environ is None else environ)
    effective={key:existing[key] if key in existing else environment.get(key) for key in INPUT_VARIABLES}
    evidence={};providers={};conflicts=[]
    aliases={'awww-daemon':'awww','swww-daemon':'swww'}
    for feature,component in (('input','input-method'),('notifications','notifications'),('wallpaper','wallpaper')):
        owners=audit_result['owners'].get(component,[])
        evidence[feature]=[dict(row) for row in owners]
        candidates=[]
        for row in owners:
            executable=_provider_executable(row['argv']);provider=aliases.get(executable,executable)
            if provider not in FEATURE_MANIFEST[feature]['providers']:
                conflicts.append({'feature':feature,'kind':'unrecognized-provider-command','owner':row})
            else:candidates.append(provider)
        if len(owners)>1:conflicts.append({'feature':feature,'kind':'multiple-configured-owners','owners':owners})
        if len(owners)==1 and len(candidates)==1:providers[feature]=candidates[0]
    env_candidates=set()
    for key,value in effective.items():
        if not value:continue
        tokens=re.split(r'[;,:\s]+',str(value).replace('@im=',''))
        selected={'ibus-daemon' if token=='ibus' else 'fcitx5' for token in tokens if token in ('ibus','fcitx','fcitx5')}
        if selected:
            evidence['input'].append({'origin':'niri-environment' if key in existing else 'process-environment','key':key,'value':value,'providers':sorted(selected)})
            env_candidates.update(selected)
    current=providers.get('input')
    normalized='fcitx5' if current=='fcitx' else current
    if len(env_candidates)>1 or (normalized and env_candidates and env_candidates!={normalized}):
        conflicts.append({'feature':'input','kind':'input-environment-owner-conflict','owner':current,'environment_providers':sorted(env_candidates)})
    elif not current and len(env_candidates)==1:providers['input']=next(iter(env_candidates))
    conflicts += [{'feature':'input','kind':'unparsed-input-environment','detail':item} for item in unknown]
    conflicts += [{'feature':None,'kind':'unknown-startup-owner','detail':item} for item in audit_result['unknown']]
    for row in conflicts:
        if row['feature']:providers.pop(row['feature'],None)
    return {'schema_version':1,'providers':providers,'evidence':evidence,'conflicts':conflicts,
            'source_hashes':{**audit_result['source_hashes'],**env_hashes},
            'policy':'configured owner and effective input environment precede installed-program order'}


def feature_plan(mode, manager, selected=None, which=None, provider_hints=None, *, font_probe=None,
                 include_file_manager=None):
    """Return a JSON-serializable plan; do not conflate installed with working."""
    if manager not in MANAGERS:
        raise ValueError('Unsupported package manager: ' + str(manager))
    which = which or shutil.which
    selected = selected_features(mode, selected)
    if mode != 'fresh' or include_file_manager is False:
        selected = [key for key in selected if key != 'file-manager']
    elif include_file_manager is True and 'file-manager' not in selected:
        selected.append('file-manager')
    hints=provider_hints or {'providers':{},'evidence':{},'conflicts':[],'source_hashes':{}}
    conflicts=[dict(row) for row in hints['conflicts'] if row.get('feature') is None or row['feature'] in selected]
    blocked={row.get('feature') for row in conflicts}
    if None in blocked:blocked.update(key for key in selected if 'providers' in FEATURE_MANIFEST[key])
    rows = []
    for key in selected:
        feature = FEATURE_MANIFEST[key]
        configured=hints['providers'].get(key)
        provider = configured or next((name for name in feature.get('providers', ()) if which(name)), None)
        if configured and not which(configured):
            conflicts.append({'feature':key,'kind':'configured-provider-unavailable','provider':configured})
            blocked.add(key)
        if key in blocked:provider=None
        needed = list(feature['packages'][manager])
        # Keep the installed input method / locker / wallpaper implementation.
        if provider and key in ('lock', 'wallpaper'):
            needed = []
        elif key == 'input' and provider in ('ibus-daemon','fcitx'):
            needed = []
        if key == 'notifications' and not provider:
            needed += feature['provider_packages'][manager]
        if key == 'preview' and not any(which(name) for name in ('wireplumber', 'pipewire-media-session')):
            needed += ['wireplumber']
        if key == 'audio' and not any(which(name) for name in ('pulseaudio', 'pipewire-pulse')):
            # Only choose a new server when neither implementation is installed.
            needed += packages('pipewire-pulse', 'pipewire-pulse', 'pipewire-pulseaudio')[manager]
        if key in blocked and key in ('input','notifications','wallpaper'):
            needed=[] if key!='notifications' else list(feature['packages'][manager])
        rows.append({'id': key, 'label': feature['label'], 'packages': needed,
                     'provider': provider, 'configs': feature['configs'], 'services': feature['services'],
                     'provider_policy':'review-conflict' if key in blocked else 'preserve-configured' if configured else 'installed-or-default',
                     'provider_evidence':hints['evidence'].get(key,[]),
                     'acceptance': feature['acceptance'],
                     'missing_commands': [' | '.join(group) for group in feature['commands']
                                          if not any(which(name) for name in group)]})
    from adws_fonts import text_font_plan
    text_fonts=text_font_plan(manager,probe=font_probe)
    return {'manifest_version': MANIFEST_VERSION, 'mode': mode, 'manager': manager,
            'configuration': MODE_MANIFESTS[mode]['configuration'], 'features': rows,
            'packages': list(dict.fromkeys([package for row in rows for package in row['packages']]+text_fonts['packages'])),
            'text_fonts':text_fonts,
            'provider_hints':hints,'conflicts':conflicts,
            'requires_repository_resolution': True}


def probe_features(selected=None, which=None):
    """Readiness checks only. Session/hardware acceptance is a separate stage."""
    which = which or shutil.which
    selected = selected_features('integrate', selected)
    results = {}
    for key in selected:
        missing = [' | '.join(group) for group in FEATURE_MANIFEST[key]['commands']
                   if not any(which(name) for name in group)]
        results[key] = {'status': 'missing' if missing else 'ready', 'missing': missing,
                        'acceptance': 'pending'}
    if 'preview' in selected or 'screenshot' in selected:
        from adws_runtime_dependencies import missing_dependencies
        runtime = missing_dependencies()
        for feature, group in [('preview', 'preview'), ('screenshot', 'capture')]:
            if feature in results and runtime.get(group):
                results[feature]['missing'] = list(dict.fromkeys(results[feature]['missing'] + runtime[group]))
                results[feature]['status'] = 'missing'
    return results


def legacy_runtime_packages():
    """Compatibility groups consumed by setup; maintain package lists once."""
    return {manager: {'capture': FEATURE_MANIFEST['screenshot']['packages'][manager],
                      'preview': FEATURE_MANIFEST['preview']['packages'][manager],
                      'preview-session': ['wireplumber']} for manager in MANAGERS}

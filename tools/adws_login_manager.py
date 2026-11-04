"""Read-only login manager and session-directory detection; no service changes."""
import configparser
from pathlib import Path
import re
import subprocess

NAMES={'sddm':'SDDM','plasmalogin':'Plasma Login Manager','gdm':'GDM','lightdm':'LightDM'}


def identify(text):
    for name,pattern in [('plasmalogin',r'\b(?:plasmalogin|plasma-login-manager)\b'),('sddm',r'\bsddm\b'),('gdm',r'\bgdm3?\b'),('lightdm',r'\blightdm\b')]:
        if re.search(pattern,text,re.I):return name
    return None


def read_ini(paths):
    config=configparser.ConfigParser(interpolation=None,strict=False)
    config.optionxform=str
    for path in paths:
        if path.is_file():
            try:
                with path.open(encoding='utf-8') as stream:config.read_file(stream)
            except configparser.Error as error:raise ValueError(f'Invalid login manager configuration: {path}: {error}') from error
    return config


def detect(root=Path('/'),runner=subprocess.run):
    root=Path(root)
    configured=None
    alias=root/'etc/systemd/system/display-manager.service'
    if alias.is_symlink():configured=identify(str(alias.readlink()))
    # An installed package is not evidence that it is the selected login manager.
    active=None
    if root==Path('/'):
        try:
            result=runner(['systemctl','show','display-manager.service','-p','Id','-p','ActiveState','-p','FragmentPath','-p','ExecStart','--no-pager'],capture_output=True,text=True,timeout=5)
            if result.returncode==0:
                detected=identify(result.stdout)
                if 'ActiveState=active' in result.stdout:active=detected
                elif not configured:configured=detected
        except (OSError,subprocess.SubprocessError):pass
    if not configured and (default:=root/'etc/X11/default-display-manager').is_file():
        configured=identify(default.read_text())
    manager=active or configured
    directories=[Path('/usr/share/wayland-sessions'),Path('/usr/local/share/wayland-sessions')]
    warning=''
    if manager=='sddm':
        paths=[*sorted((root/'usr/lib/sddm/sddm.conf.d').glob('*.conf')),
               *sorted((root/'usr/local/lib/sddm/sddm.conf.d').glob('*.conf')),
               *sorted((root/'etc/sddm.conf.d').glob('*.conf')),root/'etc/sddm.conf']
        cfg=read_ini(paths)
        value=cfg.get('Wayland','SessionDir',fallback=None)
        if value is not None:directories=[Path(part.strip()) for part in value.split(',') if part.strip()]
    elif manager=='gdm':
        cfg=read_ini([root/'etc/gdm3/daemon.conf',root/'etc/gdm/custom.conf',root/'run/gdm/custom.conf'])
        if cfg.get('daemon','WaylandEnable',fallback='true').lower()=='false':warning='wayland-disabled'
    elif manager=='lightdm':
        cfg=read_ini([*sorted((root/'usr/share/lightdm/lightdm.conf.d').glob('*.conf')),
                      *sorted((root/'etc/lightdm/lightdm.conf.d').glob('*.conf')),root/'etc/lightdm/lightdm.conf'])
        value=cfg.get('LightDM','sessions-directory',fallback=None)
        if value is not None:
            values=[Path(part.strip()) for part in value.split(':') if part.strip()]
            directories=[path for path in values if path.name=='wayland-sessions']
    # Plasma Login Manager uses QStandardPaths::GenericDataLocation, not SDDM's
    # SessionDir option. System-wide /usr/share is shared by both defaults.
    if any(not path.is_absolute() or '..' in path.parts for path in directories):
        raise ValueError('Invalid Wayland session directory in login manager configuration')
    return {'id':manager,'name':NAMES.get(manager,'unknown'),'configured':configured,'active':active,
            'session_dirs':directories,'warning':warning}


def session_entries(login,root=Path('/')):
    root=Path(root)
    entries=[]
    for directory in login['session_dirs']:
        actual=root/str(directory).lstrip('/')
        for path in sorted(actual.glob('*.desktop')):
            cfg=read_ini([path]);section='Desktop Entry'
            if not cfg.has_section(section) or cfg.get(section,'Hidden',fallback='false').lower()=='true':continue
            command=cfg.get(section,'Exec',fallback='')
            if re.search(r'(?:^|[/\s"\'])niri(?:-session|-adws)?(?:[\s"\']|$)',command):entries.append(path)
    return entries

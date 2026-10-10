"""One explicit ADWS default terminal, shared by desktop and Start actions."""
import json
import os
from pathlib import Path
import shutil
from gi.repository import Gio, GLib
from .i18n import tr as _tr

KNOWN = {'kitty','foot','alacritty','konsole','gnome-terminal','xterm','wezterm','tilix','xfce4-terminal','ptyxis','ghostty'}


def path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/default-terminal.json'


def current():
    try:
        value=json.loads(path().read_text()).get('desktop_id')
        return value if isinstance(value,str) and value and '/' not in value else None
    except (OSError,ValueError,AttributeError):return None


def choices(applications):
    return [app for app in applications if isinstance(app,Gio.DesktopAppInfo) and app.should_show()
            and not app.get_boolean('Terminal') and ('TerminalEmulator' in (app.get_categories() or '').split(';')
            or Path(app.get_executable() or '').name in KNOWN)]


def configured_argv():
    value=current()
    if not value:return None
    try:info=Gio.DesktopAppInfo.new(value)
    except TypeError:return None
    if not info or info.get_boolean('Terminal'):return None
    try:_,args=GLib.shell_parse_argv(info.get_string('Exec') or '')
    except GLib.Error:return None
    result=[]
    for item in args:
        if item in ('%f','%F','%u','%U','%i'):continue
        if '%' in item:
            if item=='%c':item=info.get_name()
            elif item=='%k':item=info.get_filename()
            elif '%' in item.replace('%%',''):continue
            else:item=item.replace('%%','%')
        result.append(item)
    binary=shutil.which(result[0]) if result else None
    return [binary,*result[1:]] if binary else None


def set_default(desktop_id):
    if desktop_id is None:
        path().unlink(missing_ok=True)
        return
    if desktop_id not in {app.get_id() for app in choices(Gio.AppInfo.get_all())}:
        raise ValueError(_tr('所选终端不可用，请刷新后重试。'))
    destination=path();destination.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    fd,name=tempfile.mkstemp(prefix='.default-terminal-',dir=destination.parent)
    try:
        with os.fdopen(fd,'w') as out:json.dump({'desktop_id':desktop_id},out);out.flush();os.fsync(out.fileno())
        os.replace(name,destination)
    finally:
        if os.path.exists(name):os.unlink(name)

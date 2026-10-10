"""Deploy bundled terminal appearance presets with backups and rollback."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from adws_i18n import tr as _tr

ROOT = Path(__file__).resolve().parents[1] / 'samples/terminal-presets'
FILES = {'kitty': ('kitty.conf', 'current-theme.conf', 'themes/matugen.conf'),
         'alacritty': ('alacritty.toml',)}


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')


def installed(name):
    return name in FILES and bool(shutil.which(name))


def font_available():
    try:
        output = subprocess.run(['fc-match', '-f', '%{family}', 'JetBrains Maple Mono'],
                                capture_output=True, text=True, timeout=3, check=True).stdout
        return 'JetBrains Maple Mono' in output.split(',')
    except (OSError, subprocess.SubprocessError):
        return False


def prepare(name):
    if name not in FILES: raise ValueError(_tr('未知终端预设。'))
    contents = {file: (ROOT/name/file).read_text() for file in FILES[name]}
    fallback = not font_available()
    shell = shutil.which('zsh') or os.environ.get('SHELL') or '/bin/sh'
    if not os.path.isabs(shell) or not os.access(shell, os.X_OK): shell = '/bin/sh'
    if name == 'kitty':
        contents['kitty.conf'] = re.sub(r'^shell .*$', 'shell '+shell, contents['kitty.conf'], flags=re.M)
        if fallback:
            contents['kitty.conf'] = re.sub(r'^font_family .*$', 'font_family monospace', contents['kitty.conf'], flags=re.M)
    else:
        contents['alacritty.toml'] = contents['alacritty.toml'].replace('program = "/bin/zsh"', 'program = '+json.dumps(shell))
        if fallback:
            contents['alacritty.toml'] = contents['alacritty.toml'].replace('"JetBrains Maple Mono"', '"monospace"')
    return contents, fallback


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.adws-preset-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out: out.write(content);out.flush();os.fsync(out.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def deploy(name):
    contents, fallback = prepare(name)
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/terminal-presets'
    state.mkdir(parents=True, exist_ok=True)
    with (state/'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-')+name+'-', dir=state))
        written = []
        originals = {}
        # Resolve an existing symlink, preserving a user's dotfiles structure.
        targets = {file: (config_home()/name/file).resolve() for file in contents}
        for file, target in targets.items():
            originals[file] = target.read_bytes() if target.exists() else None
            if target.exists():
                saved = backup/file;saved.parent.mkdir(parents=True, exist_ok=True);shutil.copy2(target, saved)
        try:
            for file, content in contents.items():
                write(targets[file], content);written.append(file)
        except Exception:
            for file in reversed(written):
                target = targets[file]
                if originals[file] is None: target.unlink(missing_ok=True)
                else: write(target, originals[file].decode('utf-8'))
            raise
        (backup/'manifest.json').write_text(json.dumps({'terminal':name,'targets':{key:str(value) for key,value in targets.items()}},indent=2))
    return {'backup': str(backup), 'font_fallback': fallback}

"""Install scoped Niri floating rules independently of autostart preferences."""
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
BEGIN = '// ==== ADWS settings windows ===='
END = '// ==== ADWS settings windows END ===='
PATTERN = re.compile(r'(?ms)^[ \t]*' + re.escape(BEGIN) + r'[^\n]*\n.*?^[ \t]*' + re.escape(END) + r'[^\n]*\n?')


def config_path():
    override = os.environ.get('NIRI_CONFIG')
    return Path(override).expanduser() if override else Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'niri/config.kdl'


def compose(text):
    if text.count(BEGIN) != text.count(END):
        raise ValueError('Incomplete ADWS settings window rule markers')
    rules = (ROOT/'config/adws-windows.kdl').read_text().strip()
    block = BEGIN + '\n' + rules + '\n' + END + '\n'
    if PATTERN.search(text):
        return PATTERN.sub(lambda _: block, text)
    return text.rstrip() + '\n\n' + block


def install(path=None):
    path = path or config_path()
    # Do not create a rules-only config that hides Niri's default key bindings.
    if not path.is_file():
        return False
    from adws_autostart import write_config
    write_config(path, compose(path.read_text()))
    return True


if __name__ == '__main__':
    install()

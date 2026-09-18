"""Offer Niri startup integration after successful installation."""
from mnws_i18n import tr as _tr
import json
import os
from pathlib import Path
import re
import shutil
import sys
import shlex
import subprocess
import tempfile
from mnws_launcher import ask

ROOT = Path(__file__).resolve().parent.parent
BEGIN = '// ==== MNWS 自启（自动生成）===='
END = '// ==== MNWS 自启 END ===='
PATTERN = re.compile(r'(?ms)^[ \t]*' + re.escape(BEGIN) + r'[^\n]*\n.*?^[ \t]*' + re.escape(END) + r'[^\n]*\n?')


DESKTOP_BEGIN = '// ==== MNWS 桌面图标层自启（自动生成）===='
DESKTOP_END = '// ==== MNWS 桌面图标层自启 END ===='
DESKTOP_PATTERN = re.compile(r'(?ms)^[ \t]*' + re.escape(DESKTOP_BEGIN) + r'[^\n]*\n.*?^[ \t]*' + re.escape(DESKTOP_END) + r'[^\n]*\n?')


def legacy_line():
    return 'spawn-at-startup ' + json.dumps(str(ROOT / 'src/niri-desktop-layer/start-desktop-layer'), ensure_ascii=False)


def desktop_enabled(text):
    if DESKTOP_PATTERN.search(text) or any(row.strip() == legacy_line() for row in text.splitlines()):
        return True
    for block in PATTERN.findall(text):
        for row in block.splitlines():
            try:
                argv = shlex.split(row, comments=True)
            except ValueError:
                continue
            if argv and argv[0] == 'spawn-at-startup' and any(arg in ('-s', '--start') for arg in argv):
                if 'taskbar' not in argv:
                    return True
    return False


def compose(text, desktop, taskbar):
    for begin, end in [(BEGIN, END), (DESKTOP_BEGIN, DESKTOP_END)]:
        if text.count(begin) != text.count(end):
            raise ValueError(_tr('MNWS 自启标记不完整，请检查 niri 配置。'))
    cleaned = PATTERN.sub('', DESKTOP_PATTERN.sub('', text))
    cleaned = ''.join(row for row in cleaned.splitlines(keepends=True) if row.strip() != legacy_line()).rstrip()
    blocks = []
    if taskbar:
        line = 'spawn-at-startup ' + json.dumps(str(ROOT / 'mnws'), ensure_ascii=False) + ' "taskbar" "-s"'
        blocks.append('\n'.join([BEGIN, line, END]))
    if desktop:
        blocks.append('\n'.join([DESKTOP_BEGIN, legacy_line(), DESKTOP_END]))
    return '\n\n'.join([part for part in [cleaned, *blocks] if part]) + '\n'


def write_config(path, text):
    # Resolve symlinks so the user's configuration link remains intact.
    path = path.resolve()
    if path.read_text() == text:
        return
    fd, name = tempfile.mkstemp(prefix='.mnws-autostart-', suffix='.kdl', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        if shutil.which('niri'):
            checked = subprocess.run(['niri', 'validate', '-c', str(temporary)], capture_output=True, text=True)
            if checked.returncode:
                raise ValueError(_tr('Niri 自启配置校验失败：%s') % checked.stderr.strip())
        shutil.copy2(path, path.with_suffix(path.suffix + '.mnws-autostart-bak'))
        temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def enable(path):
    write_config(path, compose(path.read_text(), desktop=True, taskbar=True))
    return _tr('已开启桌面和任务栏随 Niri 自启，下次登录生效。')


def set_desktop(path, enabled):
    text = path.read_text()
    write_config(path, compose(text, desktop=enabled, taskbar=bool(PATTERN.search(text))))


def main():
    try:
        while True:
            answer = ask(_tr('是否让 MNWS 桌面和任务栏随 Niri 自启？（Y/n/Ctrl+C）')).lower()
            if answer in ('n', 'no'):
                print(_tr('已跳过自启设置，安装已完成。'))
                return 0
            if answer in ('', 'y', 'yes'):
                break
            print(_tr('请输入 y 或 n。'))
        path = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'niri/config.kdl'
        print(enable(path))
    except (EOFError, KeyboardInterrupt):
        print(_tr('\n已跳过自启设置，安装已完成。'))
    except (OSError, ValueError) as error:
        print(''.join([_tr('安装已完成，但自启设置未完成：'), f'{error}', _tr('。请检查 Niri 配置后重新运行安装程序。')]), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

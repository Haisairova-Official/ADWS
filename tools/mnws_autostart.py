"""Offer Niri startup integration after successful installation."""
from mnws_i18n import tr as _tr
import json
import os
from pathlib import Path
import re
import shutil
import sys
from mnws_launcher import ask

ROOT = Path(__file__).resolve().parent.parent
BEGIN = '// ==== MNWS 自启（自动生成）===='
END = '// ==== MNWS 自启 END ===='
PATTERN = re.compile(r'(?ms)^[ \t]*' + re.escape(BEGIN) + r'[^\n]*\n.*?^[ \t]*' + re.escape(END) + r'[^\n]*\n?')


def enable(path):
    text = path.read_text()
    if BEGIN in text:
        return _tr('MNWS 自启已经开启。')
    old_desktop = '// ==== MNWS 桌面图标层自启（自动生成）====' in text
    legacy = 'spawn-at-startup ' + json.dumps(str(ROOT / 'src/niri-desktop-layer/start-desktop-layer'), ensure_ascii=False)
    old_desktop = old_desktop or any(line.strip() == legacy for line in text.splitlines())
    args = [str(ROOT / 'mnws'), 'taskbar', '-s'] if old_desktop else [str(ROOT / 'mnws'), '-s']
    line = 'spawn-at-startup ' + ' '.join(json.dumps(arg, ensure_ascii=False) for arg in args)
    backup = path.with_suffix(path.suffix + '.mnws-autostart-bak')
    shutil.copy2(path, backup)
    path.write_text(text.rstrip() + '\n\n' + BEGIN + '\n' + line + '\n' + END + '\n')
    return _tr('已开启桌面和任务栏随 Niri 自启，下次登录生效。')


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
    except OSError as error:
        print(''.join([_tr('安装已完成，但自启设置未完成：'), f'{error}', _tr('。请检查 Niri 配置后重新运行安装程序。')]), file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

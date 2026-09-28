"""Choose and configure the taskbar application launcher during installation."""
from adws_i18n import tr as _tr
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def rofi_theme_command():
    return "rofi -show drun -theme-str 'mainbox { background-image: none; }'"


def ask(prompt):
    print(prompt, end=' ', file=sys.stderr, flush=True)
    return input().strip()


def select_launcher():
    if shutil.which('fuzzel'):
        return 'fuzzel'
    if shutil.which('rofi'):
        return 'rofi -show drun'
    while True:
        answer = ask(_tr('未检测到启动器。是否安装 fuzzel（Y）或者自定义启动器参数（n）？（Y/n/Ctrl+C）')).lower()
        if answer == 'n':
            while True:
                command = ask(_tr('请输入完整启动命令（包含程序名和参数，Ctrl+C 取消）：'))
                if command:
                    return command
                print(_tr('启动命令不能为空。'), file=sys.stderr)
        elif answer in ('', 'y'):
            break
        else:
            print(_tr('请输入 y 或 n。'), file=sys.stderr)
    managers = [('apt-get', ['install', 'fuzzel']), ('dnf', ['install', 'fuzzel']),
                ('pacman', ['-S', 'fuzzel']), ('zypper', ['install', 'fuzzel']),
                ('apk', ['add', 'fuzzel'])]
    for manager, arguments in managers:
        executable = shutil.which(manager)
        if executable:
            command = [executable, *arguments]
            if os.geteuid() != 0:
                sudo = shutil.which('sudo')
                if not sudo:
                    raise RuntimeError(_tr('缺少 sudo，请手动安装 fuzzel 后重试，或选择自定义启动器。'))
                command.insert(0, sudo)
            result = subprocess.run(command, stdout=sys.stderr)
            if result.returncode or not shutil.which('fuzzel'):
                raise RuntimeError(_tr('fuzzel 安装未成功，已停止 ADWS 安装。'))
            return 'fuzzel'
    raise RuntimeError(_tr('无法识别包管理器，请手动安装 fuzzel 后重试，或选择自定义启动器。'))


def configure(path, command):
    from adws_layout import parse_jsonc
    # Follow an existing valid config link; do not replace the link itself.
    path = Path(path).resolve(strict=True)
    original = path.read_text()
    data = parse_jsonc(original)
    module = data.setdefault('custom/applauncher', {'format': _tr('开始'), 'tooltip': False})
    previous_format = module.get('format')
    if previous_format in (None, 'Apps', 'Start', '开始'):
        module['format'] = _tr('开始')
    if module.get('on-click') == command and module.get('format') == previous_format:
        return
    module['on-click'] = command
    # JSONC comments are retained in a backup; other settings retain their values.
    backup = path.with_name(path.name + '.adws-launcher.bak')
    if not backup.exists():
        backup.write_text(original)
    fd, temporary = tempfile.mkstemp(prefix='.adws-launcher-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--select', action='store_true')
    parser.add_argument('--apply', nargs=2, metavar=('PATH', 'COMMAND'))
    args = parser.parse_args()
    try:
        if args.select:
            print(select_launcher())
        elif args.apply:
            configure(*args.apply)
        else:
            parser.error(_tr('需要 --select 或 --apply'))
    except (EOFError, KeyboardInterrupt):
        print(_tr('\n已取消。'), file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(''.join([_tr('错误：'), f'{error}']), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

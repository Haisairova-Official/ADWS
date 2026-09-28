"""Choose and configure the taskbar application launcher during installation."""
from adws_i18n import tr as _tr
import argparse
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile


def rofi_theme_command():
    return "rofi -show drun -theme-str 'mainbox { background-image: none; }'"


def native_menu_command():
    return shlex.join(['bash', str(Path(__file__).resolve().parents[1] / 'adws'), 'start-menu'])


def ask(prompt):
    print(prompt, end=' ', file=sys.stderr, flush=True)
    if sys.stdin.isatty():
        return input().strip()
    # The installer invokes several Python helpers on the same input stream.
    # Do not read ahead and swallow answers intended for the next helper.
    data=bytearray()
    while True:
        byte=os.read(sys.stdin.fileno(),1)
        if byte == b'\n': break
        if not byte:
            if not data: raise EOFError
            break
        data.extend(byte)
    return data.decode(sys.stdin.encoding or 'utf-8').strip()


def select_launcher():
    while True:
        answer = ask(_tr('选择启动器：1 ADWS 开始菜单（默认），2 fuzzel，3 rofi，4 自定义。（1/2/3/4/Ctrl+C）')).lower()
        if answer in ('', '1', 'adws'):
            return native_menu_command()
        if answer in ('4', 'custom'):
            while True:
                command = ask(_tr('请输入完整启动命令（包含程序名和参数，Ctrl+C 取消）：'))
                if command:
                    return command
                print(_tr('启动命令不能为空。'), file=sys.stderr)
        program = {'2': 'fuzzel', 'fuzzel': 'fuzzel', '3': 'rofi', 'rofi': 'rofi'}.get(answer)
        if not program:
            print(_tr('请输入 1、2、3 或 4。'), file=sys.stderr)
            continue
        if not shutil.which(program):
            confirm = ask(_tr('未检测到 %s，是否现在安装？（Y/n/Ctrl+C）') % program).lower()
            if confirm not in ('', 'y'):
                continue
            install_launcher(program)
        return program if program == 'fuzzel' else 'rofi -show drun'


def install_launcher(program):
    managers = [('apt-get', ['install']), ('dnf', ['install']),
                ('pacman', ['-S']), ('zypper', ['install']), ('apk', ['add'])]
    for manager, arguments in managers:
        executable = shutil.which(manager)
        if executable:
            command = [executable, *arguments, program]
            if os.geteuid() != 0:
                sudo = shutil.which('sudo')
                if not sudo:
                    raise RuntimeError(_tr('缺少 sudo，请手动安装启动器后重试。'))
                command.insert(0, sudo)
            result = subprocess.run(command, stdout=sys.stderr)
            if result.returncode or not shutil.which(program):
                raise RuntimeError(_tr('%s 安装未成功，已停止 ADWS 安装。') % program)
            return
    raise RuntimeError(_tr('无法识别包管理器，请手动安装启动器，或选择 ADWS 开始菜单。'))


def save_selection(command):
    from adws_layout import load_layout, save_layout
    layout = load_layout()
    options = layout.setdefault('options', {})
    options['start_launcher_mode'] = ('adws' if command == native_menu_command() else
        'fuzzel' if command == 'fuzzel' else 'rofi' if command == 'rofi -show drun' else 'custom')
    options['start_launcher_command'] = command
    save_layout(layout)


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
    parser.add_argument('--save-selection')
    parser.add_argument('--apply', nargs=2, metavar=('PATH', 'COMMAND'))
    args = parser.parse_args()
    try:
        if args.save_selection:
            save_selection(args.save_selection)
        elif args.select:
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

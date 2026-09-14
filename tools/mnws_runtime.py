"""Start and stop MNWS components without matching unrelated command lines."""
from mnws_i18n import tr as _tr
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import sys

ROOT = Path(__file__).resolve().parent.parent


def matches(component, argv):
    if not argv:
        return False
    name = Path(argv[0]).name
    if component == "desktop":
        script = argv[1] if name.startswith("python") and len(argv) > 1 else argv[0]
        return Path(script).name == "desktop-layer" and "--preview" not in argv
    if name != "waybar":
        return False
    for i, arg in enumerate(argv):
        value = argv[i + 1] if arg in ("-c", "--config") and i + 1 < len(argv) else arg.removeprefix("--config=") if arg.startswith("--config=") else ""
        if value and Path(value).name == "config-bottom.jsonc":
            return True
    return False


def pids(component):
    result = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            argv = (entry / 'cmdline').read_bytes().decode(errors='replace').rstrip('\0').split('\0')
            if matches(component, argv):
                result.append(int(entry.name))
        except OSError:
            continue
    return result




def start_taskbar(config, style):
    """Verify files and detect early exit; preserve startup errors in a log."""
    from mnws_health import validate_waybar, state_home
    errors = validate_waybar(config, style)
    if errors:
        return False, '\n'.join(errors)
    log = state_home() / 'mnws/taskbar.log'
    env = dict(os.environ)
    env.pop('GDK_BACKEND', None)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('ab') as output:
            output.write(b'\n--- MNWS taskbar start ---\n')
            output.flush()
            child = subprocess.Popen(['waybar', '-c', str(config), '-s', str(style)], env=env,
                                     start_new_session=True, stdout=output, stderr=output)
        time.sleep(.5)
        code = child.poll()
        if code is not None:
            return False, ''.join([_tr('任务栏启动失败（退出码 '), f'{code}', _tr('），日志：'), f'{log}'])
    except OSError as error:
        return False, ''.join([_tr('任务栏启动失败：'), f'{error}', _tr('；日志：'), f'{log}'])
    return True, ''

def build_info():
    try:
        info = json.loads((ROOT / 'build-info.json').read_text(encoding='utf-8'))
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def version_text(info):
    if info.get('release_label'):
        return f"{info.get('major_version', _tr('未知'))} {info['release_label']}"
    return f"Major {info.get('major_version', _tr('未知'))}    Minor：{info.get('minor_version', _tr('未知'))}"


def help_text(component=None):
    title = "MNWS — My Niri Workspace Solution"
    info = build_info()
    minor = info.get('minor_version', _tr('未知'))
    major = info.get('major_version', _tr('未知'))
    build_date = info.get('build_date', _tr('未知'))
    changes = info.get('changes', [])
    if not isinstance(changes, list):
        changes = []
    summary = '\n'.join(f'  · {_tr(entry)}' for entry in changes if isinstance(entry, str)) or _tr('  暂无更新摘要。')
    if component:
        commands = ""
        usage = ''.join(['mnws ', f'{component}', _tr(' <选项>')])
    else:
        usage = _tr('mnws <命令> [选项]')
        commands = _tr('全局选项：\n  -v                   仅显示版本\n  --status             同时查看桌面和任务栏状态\n  --uninstall          卸载 MNWS（默认取消，可选择保留配置）\n\n命令：\n  desktop              管理桌面图标和桌面右键菜单\n  taskbar              管理底部任务栏\n  config               打开设置（--tab desktop|taskbar|components）\n  check                检查组件与配置状态\n  install              安装配置和命令入口\n  autostart            桌面登录自启：on / off / status\n  layout               组件布局：show / render / apply / gui\n  mplg                 插件管理：init / build / add / list / run / validate\n  build-taskbar        编译并安装任务栏模块\n  restart              重启组件：desktop / taskbar\n  help                 显示此帮助\n\n')
    if component is None:
        commands = commands.replace("  -v", _tr("  -u, --update         检查 GitHub Release 更新（不自动安装）\n") + "  -v", 1)
    target = component or "desktop"
    return ''.join([f'{title}', '\n', f'{version_text(info)}', _tr('     构建日期：'), f'{build_date}', _tr('\n\n最新更新：\n'), f'{summary}', _tr('\n\n用法：'), f'{usage}', '\n\n', f'{commands}', _tr('组件选项（desktop / taskbar；每次选择一项）：\n  -s, --start           后台启动；已运行时不重复启动\n  -S, --stop            正常停止\n  -k, --kill            强制结束\n  -r, --restart         正常停止后重新启动\n  -d, --debug           在当前终端运行并输出日志；Ctrl+C 结束\n      --status          查询运行状态与 PID\n  -h, --help, -?        显示帮助\n\n日志级别（仅用于 --debug，默认 -4）：\n  -1 致命   -2 错误   -3 警告   -4 信息   -5 调试   -6 跟踪\n\n示例：\n  mnws -s\n  mnws -s '), f'{target}', '\n  mnws ', f'{target}', ' -s\n  mnws ', f'{target}', ' -d -6\n  mnws ', f'{target}', _tr(' --status\n\n组件与选项可前后互换；省略组件时，启停、重启和状态查询同时作用于桌面和任务栏。\n调试须指定一个组件。启动成功不输出提示；失败时输出错误。\n调试模式先停止旧实例；结束后用 -s 恢复后台运行。\n停止 desktop 后桌面右键失效；--status 未运行时返回 1。\n\n我不知道 MNWS 含不含有超级牛力。\n')])


class HelpParser(argparse.ArgumentParser):
    def format_help(self):
        return help_text(self.component_help)


def moo(argv):
    if argv == ['moo']:
        print(_tr('这里应该有个彩蛋吗？'))
        return 0
    others = [arg for arg in argv if arg != 'moo']
    if len(argv) != 2 or argv.count('moo') != 1 or len(others) != 1:
        print(_tr('不，不是这样用的。'))
        return 0
    flag = others[0]
    if not flag.startswith('-v') or set(flag[1:]) != {'v'}:
        print(_tr('不，不是这样用的。'))
        return 0
    count = len(flag) - 1
    messages = (
        _tr('这个程序需要这样的彩蛋吗？'),
        _tr('这个程序我真没打算加入彩蛋。'),
        _tr('你真的有够无聊的。'),
        _tr('别玩了！做点更有意义的事去吧！'),
        _tr('我叫你停下。'),
        _tr('好吧，好吧。如果我给你彩蛋，你会满意吗？'),
    )
    if count <= len(messages):
        print(messages[count - 1], flush=True)
    if count == 7:
        try:
            subprocess.Popen(['xdg-open', 'https://www.bilibili.com/video/BV1GJ411x7h7'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass
    if count >= 8:
        print(_tr('喜欢吗？'))
    return 0

def main(argv=None, quiet=False):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "moo" in argv:
        return moo(argv)
    if len(argv) == 1 and argv[0].startswith('-v') and set(argv[0][1:]) == {'v'}:
        if argv[0] == '-v':
            info = build_info()
            print(version_text(info))
        else:
            print(_tr('不，不是这样用的。'))
        return 0
    parser = HelpParser(prog="mnws", add_help=False)
    parser.component_help = next((arg for arg in argv if arg in ('desktop', 'taskbar')), None)
    parser.add_argument('-h', '--help', '-?', action='help')
    parser.add_argument('component', nargs='?', choices=('desktop', 'taskbar'))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--start', '-s', action='store_true')
    action.add_argument('--stop', '-S', action='store_true')
    action.add_argument('--kill', '-k', action='store_true')
    action.add_argument('--debug', '-d', action='store_true', help=_tr('在当前终端运行并输出调试日志'))
    action.add_argument('--status', action='store_true', help=_tr('查询运行状态'))
    action.add_argument('--restart', '-r', action='store_true', help=_tr('正常停止后重新启动'))
    verbosity = parser.add_mutually_exclusive_group()
    for level in range(1, 7):
        verbosity.add_argument(f'-{level}', dest='log_level', action='store_const', const=level,
                               help=(_tr('致命'), _tr('错误'), _tr('警告'), _tr('信息（默认）'), _tr('调试'), _tr('跟踪'))[level - 1])
    args = parser.parse_args(argv)
    if args.log_level is not None and not args.debug:
        parser.error(_tr('-1 到 -6 仅用于 --debug/-d'))
    if args.component is None:
        if args.debug:
            parser.error(_tr('调试需要指定 desktop 或 taskbar，例如 mnws -d desktop -6'))
        operation = next('--' + name for name in ('start', 'stop', 'kill', 'restart', 'status') if getattr(args, name))
        results = [main([component, operation], quiet=quiet) for component in ('desktop', 'taskbar')]
        return max(results)
    level = args.log_level or 4
    targets = pids(args.component)
    if args.status:
        print(f'{args.component}: ' + (_tr('运行中，PID: ') + ', '.join(map(str, targets)) if targets else _tr('未运行')))
        return 0 if targets else 1
    if args.debug or args.restart:
        env = dict(os.environ)
        env.pop('GDK_BACKEND', None)
        if args.debug:
            env['PYTHONUNBUFFERED'] = '1'
            env['MNWS_LOG_LEVEL'] = str(level)
            env.pop('MNWS_PANEL_DEBUG', None)
            if args.component == 'desktop':
                command = [str(ROOT / 'src/niri-desktop-layer/desktop-layer'), '--debug', '--log-level', str(level)]
                options = {}
                for pid in targets:
                    try:
                        running = (Path('/proc') / str(pid) / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
                        for flag in ('--state', '--config', '--directory', '--monitor'):
                            if flag in running:
                                options[flag] = running[running.index(flag) + 1]
                        break
                    except (OSError, ValueError, IndexError):
                        continue
                options.setdefault('--state', str(ROOT / 'src/niri-desktop-layer/state/layout.json'))
                for flag, value in options.items():
                    command.extend([flag, value])
            else:
                folder = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'waybar'
                config, style = folder / 'config-bottom.jsonc', folder / 'style-bottom.css'
                if not config.is_file() or not style.is_file():
                    parser.exit(1, _tr('缺少任务栏配置，请先运行 mnws install。\n'))
                command = ['waybar', '-c', str(config), '-s', str(style), '-l', ('critical', 'error', 'warning', 'info', 'debug', 'trace')[level - 1]]
                env['RUST_LOG'] = ('off', 'error', 'warn', 'info', 'debug', 'trace')[level - 1]
                if level >= 5:
                    env['MNWS_PANEL_DEBUG'] = '1'
        if targets:
            if main([args.component, '--stop'], quiet=True) != 0:
                return 1
        if args.restart:
            return main([args.component, '--start'])
        try:
            os.execvpe(command[0], command, env)
        except OSError as error:
            parser.exit(1, ''.join([_tr('调试启动失败：'), f'{error}', '\n']))
        return 0
    if args.start:
        if targets:
            return 0
        if args.component == 'desktop':
            env = dict(os.environ)
            env.pop('GDK_BACKEND', None)
            return subprocess.call([str(ROOT / 'src/niri-desktop-layer/start-desktop-layer')], env=env, stdout=subprocess.DEVNULL)
        folder = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'waybar'
        config, style = folder / 'config-bottom.jsonc', folder / 'style-bottom.css'
        if not config.is_file() or not style.is_file():
            parser.exit(1, _tr('缺少任务栏配置，请先运行 mnws install。\n'))
        ok, message = start_taskbar(config, style)
        if not ok:
            parser.exit(1, message + '\n')
        return 0
    for pid in targets:
        try:
            os.kill(pid, signal.SIGKILL if args.kill else signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 3
    while set(targets) & set(pids(args.component)):
        if time.monotonic() >= deadline:
            parser.exit(1, _tr('组件尚未退出，可使用 --kill / -k 强制结束。\n'))
        time.sleep(.05)
    if not quiet:
        print(_tr('组件已停止。') if targets else _tr('组件未运行。'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

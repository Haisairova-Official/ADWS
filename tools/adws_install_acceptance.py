"""Conservative installation acceptance, separate from package readiness.

No success is inferred from an executable existing. Desktop actions require a
live session and either an explicit exercise or recorded user confirmation.
Missing session access remains pending, so a headless install cannot be called
fully accepted. This module never enables services or changes user settings.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from adws_fonts import probe_text_fonts

SCHEMA_VERSION = 1
CHECKS = ('taskbar', 'preview', 'screenshot', 'clipboard', 'launch', 'text-fonts')
MANUAL = {'preview': '打开任务栏窗口预览，确认出现真实窗口画面',
          'clipboard': '复制一段文本，在 ADWS 剪贴板中选择并粘贴，确认内容一致',
          'launch': '通过 ADWS 启动所选默认应用，确认窗口正常显示',
          'screenshot': '通过默认截图快捷键截图，确认图片内容正常'}


def _bottom_bar_states(proc=Path('/proc')):
    """Find this user's bottom bars, including ones still loading components."""
    found = []
    try: entries = list(proc.iterdir())
    except OSError: return found
    for entry in entries:
        if not entry.name.isdigit(): continue
        try:
            if entry.stat().st_uid != os.getuid(): continue
            argv = (entry/'cmdline').read_bytes().decode().rstrip('\0').split('\0')
            if not argv or Path(argv[0]).name != 'waybar': continue
            configs = [argv[i+1] for i, value in enumerate(argv[:-1]) if value in ('-c', '--config')]
            configs += [value.partition('=')[2] for value in argv if value.startswith('--config=')]
            if not any(Path(value).name == 'config-bottom.jsonc' for value in configs): continue
        except (OSError, UnicodeError): continue
        state = {'pid':int(entry.name), 'loaded':False}
        try:
            maps = (entry/'maps').read_text()
            state['loaded'] = any(line.rsplit('/',1)[-1].removesuffix(' (deleted)') == 'libniri_taskbar.so'
                                  for line in maps.splitlines())
        except (OSError, UnicodeError):
            state['error'] = 'unreadable'
        found.append(state)
    return found


def _bottom_taskbars(proc=Path('/proc')):
    """Return only verified bars; process existence alone is never readiness."""
    return [row['pid'] for row in _bottom_bar_states(proc) if row['loaded']]


def _taskbar_readiness(proc, clock, sleep):
    started = clock()
    deadline = started + 5.0
    expected_pid = None
    while True:
        bars = _bottom_bar_states(proc)
        pids = [row['pid'] for row in bars]
        reason, detail = '', ''
        if not bars:
            reason = 'not-running' if expected_pid is None else 'exited'
            detail = ('底部任务栏未运行，请启动任务栏后重新验收。' if expected_pid is None
                      else '任务栏在加载组件时退出，请查看任务栏日志后重试。')
        elif len(bars) > 1:
            reason, detail = 'duplicate', '发现多个底部任务栏，可能重复启动；请关闭多余实例后重新验收。'
        elif expected_pid is not None and bars[0]['pid'] != expected_pid:
            reason, detail = 'restarted', '任务栏在加载组件时退出并重新启动，请查看任务栏日志后重试。'
        elif bars[0].get('error'):
            reason, detail = 'unreadable', '无法读取任务栏组件的加载状态；任务栏可能已退出或当前用户没有访问权限。'
        elif bars[0]['loaded']:
            reason, detail = 'ready', '底部任务栏运行且已加载本地组件；Niri IPC 可用。'
        elif clock() >= deadline:
            reason, detail = 'loading-timeout', '任务栏已启动，但等待 5 秒后组件仍未就绪；请查看任务栏日志后重新验收。'
        if reason:
            return {'status':'passed' if reason == 'ready' else 'failed', 'kind':'runtime',
                    'detail':detail, 'runtime_state':reason, 'pids':pids,
                    'waited_ms':round(max(0,clock()-started)*1000)}
        expected_pid = bars[0]['pid']
        sleep(min(0.1, max(0, deadline-clock())))


def evaluate(selected=None, exercise=(), confirmations=(), run=None, environ=None, proc=Path('/proc'), *, clock=None, sleep=None):
    run = run or subprocess.run
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    env = dict(os.environ if environ is None else environ)
    selected = list(dict.fromkeys(CHECKS if selected is None else selected))
    unknown = set(selected) - set(CHECKS)
    if unknown: raise ValueError('Unknown acceptance checks: ' + ', '.join(sorted(unknown)))
    exercise, confirmations = set(exercise), set(confirmations)
    if exercise - {'screenshot'}: raise ValueError('Only screenshot has an automated exercise')
    if confirmations - set(MANUAL): raise ValueError('Unknown manual confirmation')
    checks = []
    live = bool(env.get('WAYLAND_DISPLAY') and env.get('XDG_RUNTIME_DIR') and env.get('NIRI_SOCKET'))
    ipc_ok = False
    ipc_detail = '需要登录目标 Niri 会话后执行验收。'
    if live and any(key!='text-fonts' for key in selected):
        try:
            result = run(['niri', 'msg', '--json', 'windows'], env=env, capture_output=True, text=True, timeout=8)
            windows = json.loads(result.stdout) if result.returncode == 0 else None
            ipc_ok = isinstance(windows, list)
            ipc_detail = 'Niri IPC 可用。' if ipc_ok else 'Niri IPC 未返回有效窗口列表。'
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            ipc_detail = 'Niri IPC 检查失败：' + str(error)
    for key in selected:
        runtime = {}
        status, kind, detail = 'pending', 'manual', MANUAL.get(key, ipc_detail)
        if key=='text-fonts':
            coverage=probe_text_fonts(environ=env)
            status='passed' if coverage['status']=='ready' else 'failed'
            kind='glyph-coverage'
            detail=('中日韩基础文字字形可用，保留用户字体选择。' if status=='passed'
                    else '中日韩文字字体缺失或无法验证，请检查字体依赖。')
            runtime={'coverage':coverage}
        elif not live:
            kind, detail = 'session', ipc_detail
        elif not ipc_ok:
            status, kind, detail = 'failed', 'session', ipc_detail
        elif key == 'taskbar':
            runtime = _taskbar_readiness(proc, clock, sleep)
            status, kind, detail = runtime['status'], runtime['kind'], runtime['detail']
        elif key == 'screenshot' and key in exercise:
            kind = 'exercise'
            try:
                with tempfile.TemporaryDirectory(prefix='adws-acceptance-') as folder:
                    target = Path(folder)/'screenshot.png'
                    result = run(['grim', str(target)], env=env, capture_output=True, text=True, timeout=15)
                    from PIL import Image
                    valid = False
                    if target.exists():
                        with Image.open(target) as image:
                            image.load()
                            valid = image.format == 'PNG' and image.width > 0 and image.height > 0
                    status = 'passed' if result.returncode == 0 and valid else 'failed'
                    detail = ('实际截图成功，临时图像已删除。' if status == 'passed'
                              else '截图未生成有效 PNG：' + (result.stderr or '').strip()[:400])
            except (ImportError, OSError, ValueError, subprocess.TimeoutExpired) as error:
                status, detail = 'failed', '截图测试失败：' + str(error)
        elif key in confirmations:
            status, kind, detail = 'passed', 'user-confirmed', MANUAL[key] + '：用户已确认。'
        checks.append({'id': key, 'status': status, 'kind': kind, 'detail': detail, **runtime})
    failed = [row['id'] for row in checks if row['status'] == 'failed']
    pending = [row['id'] for row in checks if row['status'] == 'pending']
    return {'schema_version': SCHEMA_VERSION, 'complete': bool(checks) and not failed and not pending,
            'checks': checks, 'failed': failed, 'pending': pending}


def main(argv=None):
    parser = argparse.ArgumentParser(description='ADWS 功能验收；待验收项目不会计为安装完成。')
    parser.add_argument('--checks', nargs='+', choices=CHECKS)
    parser.add_argument('--exercise', action='append', choices=['screenshot'], default=[],
                        help='实际截图到临时目录，验证后立即删除。')
    parser.add_argument('--confirm', action='append', choices=tuple(MANUAL), default=[],
                        help='交互记录已由用户实际完成的测试；不会自动标记通过。')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    confirmations = []
    for feature in args.confirm:
        if input(MANUAL[feature] + '。已完成并正常？[y/N] ').strip().lower() == 'y':
            confirmations.append(feature)
    report = evaluate(args.checks, args.exercise, confirmations)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text+'\n', encoding='utf-8')
    print(text)
    return 1 if report['failed'] else 2 if not report['complete'] else 0


if __name__ == '__main__': raise SystemExit(main())

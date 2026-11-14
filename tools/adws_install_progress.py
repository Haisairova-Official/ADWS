"""Display the running install transaction and relay its private controlling TTY."""
import codecs
import collections
import curses
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import sys
import termios
import time

from adws_install_ui import Dialog, _clip, _page, show_text

# These initial duration estimates are deliberately approximate. Actual completion
# and rollback always come from the install journal.
def stages(plan):
    result = {'packages': ('软件包事务', 90 if plan.get('system_upgrade') else 20)}
    for key, name, label in (
        ('package_owner_plan', 'package-startup-ownership', '核对启动项'),
        ('source_migration', 'installation-source-migration', '迁移安装路径'),
        ('legacy_plan', 'legacy-configuration', '迁移旧配置'),
        ('topbar_migration', 'topbar-source-migration', '更新顶栏路径'),
    ):
        if plan.get(key):
            result[name] = (label, 2)
    result['native-components'] = ('安装桌面组件', 80 if plan.get('build_fallback') else 12)
    for key, name, label in (
        ('bottom_library_migration', 'bottom-library-migration', '更新任务栏'),
        ('migration_source', 'migration', '导入个人配置'),
        ('session_plan', 'session-configuration', '配置会话'),
    ):
        if plan.get(key):
            result[name] = (label, 5)
    result['niri-configuration'] = ('配置 Niri', 4)
    if plan.get('palette_plan'):
        result['palette-registration'] = ('注册自动配色', 3)
    result['default-applications'] = ('设置默认应用', 3)
    if plan.get('startup_plan'):
        result['autostart'] = ('配置自动启动', 3)
    result['adws-configuration'] = ('部署 ADWS 配置', 10)
    if plan.get('migration_plan', {}).get('account_action', {}).get('policy') == 'set':
        result['account-nickname'] = ('设置显示昵称', 2)
    if plan.get('theme_plan', {}).get('changes'):
        result['system-themes'] = ('安装系统主题', 15)
    result['acceptance'] = ('验证安装结果', 5)
    return result


def duration(seconds):
    minutes, seconds = divmod(int(max(0, seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


def measure(expected, journal, elapsed):
    steps = journal.get('steps', {})
    done = {name for name, row in steps.items() if row.get('status') == 'passed'}
    current = next((name for name,row in steps.items() if row.get('status') == 'running'), None)
    if journal.get('deployment_receipt'):
        current = 'acceptance'
    total = sum(weight for _, weight in expected.values())
    completed = sum(expected[key][1] for key in done if key in expected)
    label, weight = expected.get(current, ('正在准备', 0))
    partial = min(elapsed, weight * .9)
    percent = min(99, int(100 * (completed + partial) / total))
    remaining = duration(total - completed - partial)
    if weight and elapsed > weight:
        remaining = '估算中'
    if journal.get('status') in ('failed', 'recovery-incomplete'):
        label, remaining = '处理失败与恢复', '估算中'
    return label, len(done), percent, remaining


def _child(operation):
    # forkpty inherits a fresh line discipline. Enable canonical input and echo
    # so sudo can manage password echo on its own /dev/tty.
    attrs = termios.tcgetattr(0)
    attrs[3] |= termios.ICANON | termios.ECHO | termios.ISIG
    termios.tcsetattr(0, termios.TCSANOW, attrs)
    signal.signal(signal.SIGWINCH, signal.SIG_DFL)
    try:
        code = operation()
    except KeyboardInterrupt:
        code = 130
    except BaseException as exc:
        print(str(exc), file=sys.stderr, flush=True)
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def monitor(plan, directory, operation):
    expected = stages(plan)
    directory = Path(directory)

    def watch(screen):
        dialog = Dialog(screen)
        output = collections.deque(maxlen=60)
        pending = ''
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        start = changed = time.monotonic()
        last_stage = None
        journal = {}
        journal_path = directory/'progress.json'
        last_size = None
        stopping = False
        sys.stdout.flush()
        sys.stderr.flush()
        pid, master = pty.fork()
        if pid == 0:
            try:
                _child(operation)
            finally:
                os._exit(1)
        status = None
        eof = False
        drain_until = None
        redraw = 0
        try:
            while status is None or not eof:
                now = time.monotonic()
                if drain_until is not None and now >= drain_until:
                    break  # A newly launched desktop process can retain the slave TTY.
                if now >= redraw:
                    size = os.get_terminal_size(0)
                    shape = (size.lines, size.columns)
                    if shape != last_size:
                        if screen.getmaxyx() != shape:
                            curses.resizeterm(*shape)
                        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', *shape, 0, 0))
                        last_size = shape
                    try:
                        journal = json.loads(journal_path.read_text())
                    except FileNotFoundError:
                        pass
                    stage = (journal.get('status'), tuple((key,row.get('status')) for key,row in journal.get('steps', {}).items()))
                    if stage != last_stage:
                        last_stage, changed = stage, now
                    label, done, percent, eta = measure(expected, journal, now - changed)
                    if dialog.frame('正在安装' if not stopping else '正在取消', 18, '提示出现时直接输入并回车  ·  Ctrl+C 取消'):
                        bar_width = dialog.cols - 6
                        filled = int(bar_width * percent / 100)
                        info = [f'请稍候 · {label}    已完成 {done} 步',
                                '━' * filled + '─' * (bar_width - filled) + f' {percent:2d}%',
                                f'估算进度  ·  已用 {duration(now-start)}  ·  预计剩余 {eta}', '']
                        # Keep the most recent prompt visible even in a short terminal.
                        slots = min(len(info), max(0, dialog.rows - 1))
                        for i, line in enumerate(info[:slots]):
                            dialog.put(dialog.y+i, dialog.x, _clip(line, dialog.cols), dialog.title if i==1 else 0)
                        log = list(output)
                        if pending:
                            log.append(pending)
                        for i, line in enumerate(log[-(dialog.rows-slots):]):
                            dialog.put(dialog.y+slots+i, dialog.x, _clip(line, dialog.cols))
                        dialog.put(dialog.actions, dialog.x, '实时输出', dialog.border)
                        screen.refresh()
                    redraw = now + .12
                try:
                    readable, _, _ = select.select(([master] if not eof else []) + ([0] if not stopping and status is None else []), [], [], .1)
                    if master in readable:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError as exc:
                            if exc.errno != errno.EIO:
                                raise
                            chunk = b''
                        if not chunk:
                            eof = True
                        else:
                            text = decoder.decode(chunk)
                            # Never interpret commands from a build log as terminal controls.
                            text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).replace('\r\n', '\n').replace('\r', '\n')
                            lines = (pending + text).split('\n')
                            clean = [''.join(ch for ch in line.expandtabs(4) if ch.isprintable())[-4096:] for line in lines]
                            output.extend(clean[:-1])
                            pending = clean[-1]
                    if 0 in readable:
                        data = os.read(0, 4096)
                        if data:
                            os.write(master, data)
                        else:
                            stopping = True
                            os.kill(pid, signal.SIGTERM)
                    if status is None:
                        waited, value = os.waitpid(pid, os.WNOHANG)
                        if waited:
                            status = os.waitstatus_to_exitcode(value)
                            drain_until = time.monotonic() + .3
                except KeyboardInterrupt:
                    if status is None and not stopping:
                        stopping = True
                        os.kill(pid, signal.SIGTERM)
        finally:
            if status is None:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                # Continue draining while transaction cleanup and rollback are logging.
                while not os.waitpid(pid, os.WNOHANG)[0]:
                    if select.select([master], [], [], .1)[0]:
                        try:
                            os.read(master, 65536)
                        except OSError:
                            time.sleep(.05)
            os.close(master)
        if stopping or status in (130, -signal.SIGTERM):
            raise KeyboardInterrupt
        if status not in (0, 2):
            raise RuntimeError('\n'.join([*list(output)[-12:], pending]).strip() or f'安装程序退出 ({status})')
        report = directory/'result.md'
        title = '安装完成' if status == 0 else '配置已部署 · 待验收'
        summary = '安装与验收已完成 · 100%' if status == 0 else '安装步骤已结束，仍有功能待验收。'
        show_text(title, summary + '\n\n' + (report.read_text() if report.is_file() else str(directory)))
        return status

    return _page(watch)

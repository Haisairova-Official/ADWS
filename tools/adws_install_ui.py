"""Terminal menus for installation and recovery; noninteractive flags stay scriptable."""
import curses
import os
import sys
import textwrap
import unicodedata


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get('TERM', '') not in ('', 'dumb')


def choose(title, labels, default=0, detail=''):
    if not interactive():
        for index, label in enumerate(labels, 1):
            print(f'{index}. {label}')
        while True:
            answer = input(f'{title} [{default + 1}] ').strip()
            if not answer:
                return default
            if answer.isdecimal() and 1 <= int(answer) <= len(labels):
                return int(answer) - 1

    return _menu(title, labels, default, detail)


def _clip(text, columns):
    used = 0
    for end, char in enumerate(text):
        used += 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in 'WF' else 1
        if used > columns:
            return text[:end]
    return text


def _menu(title, labels, default=0, detail='', checked=None):
    def draw(screen):
        selected = default
        offset = 0
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        while True:
            height, width = screen.getmaxyx()
            screen.erase()
            def line(row, text, attr=0):
                if 0 <= row < height - 1:
                    screen.addstr(row, 0, _clip(text, max(0, width - 1)), attr)
            line(0, ' ADWS 安装程序 '.ljust(width - 2), curses.A_REVERSE | curses.A_BOLD)
            row = 2
            for fragment in textwrap.wrap(title, max(8, width // 2 - 1)):
                line(row, fragment, curses.A_BOLD)
                row += 1
            details = [fragment for part in detail.splitlines()
                       for fragment in textwrap.wrap(part, max(8, width // 2 - 1))]
            page = min(len(details), max(1, (height - row - 5) // 2))
            offset = min(offset, max(0, len(details) - page))
            for fragment in details[offset:offset + page]:
                line(row, fragment)
                row += 1
            if len(details) > page:
                line(row, f' PgUp/PgDn 翻阅详情  {offset + 1}–{offset + page}/{len(details)}', curses.A_DIM)
                row += 1
            row += 1
            slots = max(1, height - row - 3)
            first = max(0, selected - slots + 1)
            for i in range(first, min(first + slots, len(labels))):
                mark = '' if checked is None else ('[✓] ' if i in checked else '[ ] ')
                line(row, (' › ' if i == selected else '   ') + mark + labels[i],
                     curses.A_REVERSE if i == selected else 0)
                row += 1
            hint = '空格 勾选   ' if checked is not None else ''
            line(height - 2, '↑↓ 选择   ' + hint + 'Enter 确认   Esc 退出')
            screen.refresh()
            key = screen.getch()
            if key in (10, 13, curses.KEY_ENTER):
                return selected
            if key in (27, ord('q')):
                raise KeyboardInterrupt
            if key == curses.KEY_PPAGE:
                offset = max(0, offset - page)
            elif key == curses.KEY_NPAGE:
                offset += page
            elif key == ord(' ') and checked is not None:
                checked.symmetric_difference_update([selected])
            elif key in (curses.KEY_UP, ord('k')):
                selected = (selected - 1) % len(labels)
            elif key in (curses.KEY_DOWN, ord('j')):
                selected = (selected + 1) % len(labels)
    return curses.wrapper(draw)


def prompt(message):
    if interactive() and message.rstrip().endswith(('[y/N]', '[Y/n]')):
        return ('n', 'y')[choose(message.rsplit('[', 1)[0], ['否', '是'], int('[Y/n]' in message))]
    return input(message)


def text_entry(title):
    if not interactive():
        return input(title)
    def edit(screen):
        value = []
        while True:
            screen.erase()
            height, width = screen.getmaxyx()
            lines = ['ADWS 安装程序', '', *textwrap.wrap(title, max(10, width // 2 - 2)),
                     '', '> ' + ''.join(value)[-max(1, width // 2 - 3):], '', 'Enter 确认   Esc 退出']
            for row, line in enumerate(lines[:height - 1]):
                screen.addnstr(row, 0, line, max(1, width - 1))
            key = screen.get_wch()
            if key in ('\n', '\r', curses.KEY_ENTER):
                return ''.join(value)
            if key == '\x1b':
                raise KeyboardInterrupt
            if key in (curses.KEY_BACKSPACE, '\b', '\x7f'):
                if value:
                    value.pop()
            elif isinstance(key, str) and key.isprintable():
                value.append(key)
    return curses.wrapper(edit)


def select_targets(title, targets, initial=(), labels=None):
    targets = list(targets)
    checked = {i for i, key in enumerate(targets) if key in initial}
    if targets:
        _menu(title, [(labels or {}).get(key, key) for key in targets], checked=checked)
    return [key for i, key in enumerate(targets) if i in checked]

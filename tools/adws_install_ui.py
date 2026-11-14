"""Terminal menus for installation and recovery; noninteractive flags stay scriptable."""
import curses
import os
import sys
import textwrap


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

    def menu(screen):
        selected = default
        while True:
            height, width = screen.getmaxyx()
            width = max(1, width - 2)
            screen.erase()
            def line(row, value, attr=0):
                if row < height - 1:
                    try:
                        screen.addnstr(row, 0, value, width, attr)
                    except curses.error:
                        pass
            line(0, 'ADWS 安装程序', curses.A_BOLD)
            row = 2
            for fragment in textwrap.wrap(title, max(10, width // 2)):
                line(row, fragment, curses.A_BOLD)
                row += 1
            for part in detail.splitlines():
                for fragment in textwrap.wrap(part, max(10, width // 2)):
                    if row >= height // 2:
                        break
                    line(row, fragment)
                    row += 1
                if row >= height // 2:
                    break
            slots = max(1, height - row - 3)
            first = max(0, selected - slots + 1)
            for i in range(first, min(first + slots, len(labels))):
                line(row, (' › ' if i == selected else '   ') + labels[i],
                     curses.A_REVERSE if i == selected else 0)
                row += 1
            line(height - 2, '↑ ↓ 选择   Enter 确认   Esc 退出')
            screen.refresh()
            key = screen.getch()
            if key in (10, 13, curses.KEY_ENTER):
                return selected
            if key in (27, ord('q')):
                raise KeyboardInterrupt
            if key in (curses.KEY_UP, ord('k')):
                selected = (selected - 1) % len(labels)
            if key in (curses.KEY_DOWN, ord('j')):
                selected = (selected + 1) % len(labels)
    return curses.wrapper(menu)


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


def select_targets(title, targets):
    selected = set()
    index = 0
    while True:
        labels = [('☑ ' if target in selected else '☐ ') + target for target in targets]
        index = choose(title, ['完成选择', *labels], index)
        if index == 0:
            return [target for target in targets if target in selected]
        selected.symmetric_difference_update([targets[index - 1]])

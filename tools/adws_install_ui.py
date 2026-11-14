"""Keyboard-driven installation dialogs with a plain terminal fallback."""
import curses
import os
import sys
import unicodedata


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get('TERM', '') not in ('', 'dumb')


_screen = None
_history = None


class Back(Exception):
    """Return to the previous decision in the current planning pass."""


class History:
    def __init__(self):
        self.answers = []
        self.position = 0
        self.previous = None


def navigate(function, *args):
    global _history
    if _screen is None:
        return function(*args)
    saved = _history
    history = History()
    _history = history
    try:
        while True:
            history.position = 0
            try:
                return function(*args)
            except Back:
                if history.position:
                    history.previous = history.answers.pop()
    finally:
        _history = saved


def _decision(identity, read):
    history = _history
    if history is None:
        return read(None)
    index = history.position
    if index < len(history.answers) and history.answers[index][0] == identity:
        history.position += 1
        return history.answers[index][1]
    del history.answers[index:]
    previous = history.previous
    history.previous = None
    value = read(previous[1] if previous and previous[0] == identity else None)
    history.answers.append((identity, value))
    history.position += 1
    return value


def run_wizard(function, *args):
    """Keep ncurses' virtual screen alive across pages and recovery dialogs."""
    if not interactive():
        return function(*args)
    def run(screen):
        global _screen
        _screen = screen
        screen.idlok(False)
        try:
            return function(*args)
        finally:
            _screen = None
    return curses.wrapper(run)


def _page(draw):
    if _screen is None:
        return curses.wrapper(draw)
    return draw(_screen)


def waiting(message):
    if _screen is not None and not (_history and _history.position < len(_history.answers)):
        height, width = _screen.getmaxyx()
        label = _clip('  请稍候 · ' + message, max(0, width - 1))
        _screen.addstr(height - 1, 0, label + ' ' * (width - 1 - _width(label)), curses.A_REVERSE)
        _screen.refresh()


def _cells(char):
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in 'WF' else 1


def _width(text):
    return sum(_cells(char) for char in text)


def _clip(text, columns):
    used = 0
    for end, char in enumerate(text):
        used += _cells(char)
        if used > columns:
            return text[:end]
    return text


def _wrap(text, width):
    rows = []
    for paragraph in text.expandtabs(4).splitlines():
        if not paragraph:
            rows.append('')
        while paragraph:
            line = _clip(paragraph, width)
            if len(line) < len(paragraph) and line.rfind(' ') > len(line) // 2:
                line = line[:line.rfind(' ') + 1]
            rows.append(line.rstrip())
            paragraph = paragraph[len(line):]
    return rows


class Dialog:
    def __init__(self, screen):
        self.screen = screen
        self.title = curses.A_BOLD
        self.border = curses.A_NORMAL
        self.selected = curses.A_REVERSE | curses.A_BOLD
        if curses.has_colors() and not os.environ.get('NO_COLOR'):
            try:
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)
                curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
                self.border = curses.color_pair(1)
                self.title |= self.border
                self.selected = curses.color_pair(2) | curses.A_BOLD
            except curses.error:
                pass
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def put(self, y, x, text, attr=0):
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and 0 <= x < width:
            # Writing the last cell of the last row scrolls some terminals.
            self.screen.addstr(y, x, _clip(text, width - x - int(y == height - 1)), attr)

    def frame(self, title, wanted, hint):
        screen = self.screen
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 9 or width < 20:
            self.put(0, 0, '请放大终端 · Esc 返回')
            screen.refresh()
            return False
        margin = 2 if width >= 48 else 0
        outer = min(82, width - 2 * margin)
        self.left = (width - outer) // 2
        self.x = self.left + (3 if outer >= 40 else 2)
        self.cols = outer - 2 * (self.x - self.left)
        headings = _wrap(title, self.cols)
        height_limit = height - (4 if height >= 16 else 1)
        # Reserve space for at least one list row and the action bar.
        headings = headings[:max(1, height_limit - 6)]
        size = min(height_limit, max(14, len(headings) + wanted + 5))
        top = (height - 1 - size) // 2
        bottom = top + size - 1
        for row in range(top + 1, bottom):
            self.put(row, self.left, '│', self.border)
            self.put(row, self.left + outer - 1, '│', self.border)
        caption = ' ADWS 安装 '
        self.put(top, self.left, '╭─' + caption + '─' * (outer - _width(caption) - 3) + '╮', self.border)
        self.put(bottom, self.left, '╰' + '─' * (outer - 2) + '╯', self.border)
        for row, line in enumerate(headings, top + 1):
            self.put(row, self.x, line, self.title)
        self.y = top + len(headings) + 2
        self.actions = bottom - 1
        self.rows = self.actions - self.y
        self.put(height - 1, self.left, hint, curses.A_DIM)
        return True

    def buttons(self, labels, focus):
        x = self.x
        for index, label in enumerate(labels):
            text = (' ' + label + ' ') if self.cols < 25 else ('‹ ' + label + ' ›')
            self.put(self.actions, x, text, self.selected if index == focus else self.border | curses.A_BOLD)
            x += _width(text) + 1


ENTER = (10, 13, curses.KEY_ENTER)
UP = (curses.KEY_UP, ord('k'))
DOWN = (curses.KEY_DOWN, ord('j'))


def _menu(title, labels, default=0, detail='', checked=None, descriptions=None):
    def draw(screen):
        dialog = Dialog(screen)
        selected = default
        previous = None
        buttons = ['确定', '返回', '退出'] if _history and _history.position else ['确定', '退出']
        first = offset = focus = 0
        while True:
            help_text = '↑↓ 选择  ' + ('空格 勾选  ' if checked is not None else '') + 'Tab 按钮  Enter 确认  Esc 返回'
            if selected != previous:
                offset = 0
                previous = selected
            description = descriptions[selected] if descriptions else detail
            ready = dialog.frame(title, min(8, len(labels)) + (5 if description else 0), help_text)
            if ready:
                row = dialog.y
                details = _wrap(description, dialog.cols)
                count = min(len(details), max(0, (dialog.rows - 2) // 2))
                offset = min(offset, max(0, len(details) - count))
                for line in details[offset:offset + count]:
                    dialog.put(row, dialog.x, line)
                    row += 1
                if count and count < len(details):
                    dialog.put(row, dialog.x, f'PgUp/PgDn 详情  {offset+1}–{offset+count}/{len(details)}', dialog.border)
                    row += 1
                slots = max(1, dialog.actions - row)
                first = max(0, min(first, selected, len(labels) - slots), selected - slots + 1)
                for i in range(first, min(len(labels), first + slots)):
                    mark = ('[x] ' if i in checked else '[ ] ') if checked is not None else ''
                    prefix = '› ' if i == selected else '  '
                    value = _clip(prefix + mark + labels[i], dialog.cols)
                    style = dialog.selected if i == selected and focus == 0 else 0
                    dialog.put(row, dialog.x, value + ' ' * (dialog.cols - _width(value)), style)
                    row += 1
                dialog.buttons(buttons, focus - 1)
                screen.refresh()
            key = screen.getch()
            if key == 27:
                if _history is not None and _history.position == 0:
                    continue
                raise Back
            if key == ord('q'):
                raise KeyboardInterrupt
            if not ready:
                continue
            if key in ENTER or (focus and key == ord(' ')):
                if focus and buttons[focus - 1] == '退出':
                    raise KeyboardInterrupt
                if focus and buttons[focus - 1] == '返回':
                    raise Back
                return selected
            if key in (9, curses.KEY_BTAB):
                focus = (focus + (1 if key == 9 else -1)) % (len(buttons) + 1)
            elif focus and key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                focus = 1 + (focus - 1 + (1 if key == curses.KEY_RIGHT else -1)) % len(buttons)
            elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
                step = -1 if key == curses.KEY_PPAGE else 1
                if count < len(details) and count:
                    offset = max(0, offset + step * count)
                else:
                    selected = max(0, min(len(labels) - 1, selected + step * slots))
            elif key == ord(' ') and checked is not None:
                checked.symmetric_difference_update([selected])
            elif key in UP + DOWN:
                focus = 0
                selected = (selected + (1 if key in DOWN else -1)) % len(labels)
            elif key in (curses.KEY_HOME, curses.KEY_END):
                focus = 0
                selected = 0 if key == curses.KEY_HOME else len(labels) - 1
    return _page(draw)


def choose(title, labels, default=0, detail='', descriptions=None):
    if interactive():
        return _decision(('menu', title, tuple(labels)),
                         lambda old: _menu(title, labels, default if old is None else old,
                                           detail, descriptions=descriptions))
    if detail:
        print(detail)
    for index, label in enumerate(labels, 1):
        print(f'{index}. {label}')
    while True:
        answer = input(f'{title} [{default + 1}] ').strip()
        if not answer:
            return default
        if answer.isdecimal() and 1 <= int(answer) <= len(labels):
            return int(answer) - 1


def show_text(title, text):
    if not interactive():
        print(text)
        return
    if _history and _history.position < len(_history.answers):
        return
    def read(screen):
        dialog = Dialog(screen)
        offset = 0
        last_width = None
        while True:
            ready = dialog.frame(title, 24, '↑↓ 滚动  PgUp/PgDn 翻页  Enter/Esc 返回')
            if ready:
                if last_width != dialog.cols:
                    lines = _wrap(text, dialog.cols)
                    last_width = dialog.cols
                limit = max(0, len(lines) - dialog.rows)
                offset = max(0, min(offset, limit))
                for i, line in enumerate(lines[offset:offset + dialog.rows]):
                    dialog.put(dialog.y + i, dialog.x, line)
                dialog.buttons(['返回'], 0)
                if lines:
                    status = f'{offset + 1}–{min(len(lines), offset + dialog.rows)}/{len(lines)}'
                    dialog.put(dialog.actions, dialog.x + dialog.cols - _width(status), status, curses.A_DIM)
                screen.refresh()
            key = screen.getch()
            if key in (*ENTER, 27, ord('q')):
                return
            if not ready:
                continue
            if key in UP + DOWN:
                offset += 1 if key in DOWN else -1
            elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE, ord(' ')):
                offset += -dialog.rows if key == curses.KEY_PPAGE else dialog.rows
            elif key in (curses.KEY_HOME, curses.KEY_END):
                offset = 0 if key == curses.KEY_HOME else limit
    _page(read)


def prompt(message):
    if interactive() and message.rstrip().endswith(('[y/N]', '[Y/n]')):
        question = message.rsplit('[', 1)[0].strip()
        default = int('[Y/n]' in message)
        if _width(question) > 54:
            return ('n', 'y')[choose('安装选项', ['否', '是'], default, detail=question)]
        return ('n', 'y')[choose(question, ['否', '是'], default)]
    return input(message)


def text_entry(title):
    if not interactive():
        return input(title)
    def edit(screen, initial):
        dialog = Dialog(screen)
        buttons = ['确定', '返回', '退出'] if _history and _history.position else ['确定', '退出']
        value = list(initial or '')
        cursor = len(value)
        focus = 0
        while True:
            ready = dialog.frame(title, 2, '←→ 移动  Tab 按钮  Enter 确认  Esc 返回')
            if ready:
                before = _clip(''.join(reversed(value[:cursor])), dialog.cols - 2)[::-1]
                at = ''.join(value[cursor:cursor+1]) or ' '
                remaining = dialog.cols - _width(before) - _width(at)
                tail = _clip(''.join(value[cursor+1:]), remaining)
                dialog.put(dialog.y, dialog.x, before + at + tail + ' ' * (remaining - _width(tail)), curses.A_UNDERLINE)
                if focus == 0:
                    dialog.put(dialog.y, dialog.x + _width(before), at, dialog.selected)
                dialog.buttons(buttons, focus - 1)
                screen.refresh()
            key = screen.get_wch()
            if key == '\x1b':
                if _history is not None and _history.position == 0:
                    continue
                raise Back
            if not ready:
                continue
            if key in ('\n', '\r', curses.KEY_ENTER) or (focus and key == ' '):
                if focus and buttons[focus - 1] == '退出':
                    raise KeyboardInterrupt
                if focus and buttons[focus - 1] == '返回':
                    raise Back
                return ''.join(value)
            if key in ('\t', curses.KEY_BTAB):
                focus = (focus + (1 if key == '\t' else -1)) % (len(buttons) + 1)
            elif focus and key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                focus = 1 + (focus - 1 + (1 if key == curses.KEY_RIGHT else -1)) % len(buttons)
            elif focus:
                continue
            elif key in (curses.KEY_BACKSPACE, '\b', '\x7f'):
                if cursor:
                    cursor -= 1
                    del value[cursor]
            elif key == curses.KEY_DC:
                del value[cursor:cursor+1]
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                cursor = max(0, min(len(value), cursor + (1 if key == curses.KEY_RIGHT else -1)))
            elif key in (curses.KEY_HOME, curses.KEY_END):
                cursor = 0 if key == curses.KEY_HOME else len(value)
            elif isinstance(key, str) and key.isprintable():
                value.insert(cursor, key)
                cursor += 1
    return _decision(('input', title), lambda old: _page(lambda screen: edit(screen, old)))


def select_targets(title, targets, initial=(), labels=None):
    targets = list(targets)
    def read(old):
        enabled = initial if old is None else old
        checked = {i for i, key in enumerate(targets) if key in enabled}
        if targets:
            _menu(title, [(labels or {}).get(key, key) for key in targets], checked=checked)
        return [key for i, key in enumerate(targets) if i in checked]
    return _decision(('checklist', title, tuple(targets)), read)

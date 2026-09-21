#!/usr/bin/env python3
"""Clock preferences shared by the Waybar renderer and settings dialog."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import os
import html
from pathlib import Path
import re
import shlex
import subprocess
import sys

from mnws_i18n import tr as _tr

DATE_FORMATS = {
    'iso': '%Y-%m-%d', 'ymd': '%Y/%m/%d',
    'dmy': '%d/%m/%Y', 'mdy': '%m/%d/%Y', 'dots': '%d.%m.%Y',
}


def time_locale(environ=None):
    env = os.environ if environ is None else environ
    return env.get('LC_ALL') or env.get('LC_TIME') or env.get('LANG') or 'C'


@lru_cache(maxsize=32)
def recommended_format(region):
    # Ask the installed locale database for regional ordering, independent of
    # MNWS's UI language. Fall back sensibly when that locale is not installed.
    try:
        result = subprocess.run(['locale', '-k', 'd_fmt'],
                                env={**os.environ, 'LC_ALL': region},
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=2)
        match = re.search(r'^d_fmt="([^"]+)"', result.stdout, re.M)
        if result.returncode == 0 and match:
            pattern = match[1].replace('%D', '%m/%d/%y').replace('%F', '%Y-%m-%d')
            parts = re.findall(r'%[EO]?([Yymde])', pattern)
            order = ['y' if p in ('Y', 'y') else 'd' if p in ('d', 'e') else 'm' for p in parts]
            if order == ['y', 'm', 'd']:
                return 'ymd' if '/' in pattern else 'iso'
            if order == ['d', 'm', 'y']:
                return 'dots' if '.' in pattern else 'dmy'
            if order == ['m', 'd', 'y']:
                return 'mdy'
    except (OSError, subprocess.SubprocessError):
        pass
    country = region.split('.')[0].split('@')[0].replace('-', '_').upper().split('_')[-1]
    if country in ('US', 'PH', 'BZ', 'FM', 'PW'): return 'mdy'
    if country in ('CN', 'JP', 'KR', 'TW', 'CA', 'SE', 'HU', 'LT'): return 'iso'
    if country in ('DE', 'AT', 'CH', 'FI', 'RU', 'CZ', 'SK', 'PL', 'TR'): return 'dots'
    if country in ('GB', 'AU', 'NZ', 'IE', 'FR', 'ES', 'IT', 'PT', 'BR', 'IN', 'ID', 'MX'): return 'dmy'
    return 'iso'


def preferences(options):
    raw = options.get('clock', {})
    raw = raw if isinstance(raw, dict) else {}
    return {'show_date': raw.get('show_date') is True,
            'show_seconds': raw.get('show_seconds') is True,
            'show_weekday': raw.get('show_weekday') is True,
            'two_lines': raw.get('two_lines') is not False,
            'custom_enabled': raw.get('custom_enabled') is True,
            'custom_format': raw.get('custom_format') if isinstance(raw.get('custom_format'), str) else 'HH:mm:SS\nYYYY-MM-DD',
            'date_format': raw.get('date_format') if raw.get('date_format') in (*DATE_FORMATS, 'auto') else 'auto'}


def date_pattern(prefs):
    key = prefs['date_format']
    return DATE_FORMATS[recommended_format(time_locale()) if key == 'auto' else key]


TOKENS = {'YYYY': '%Y', 'MM': '%m', 'DD': '%d', 'HH': '%H', 'mm': '%M', 'SS': '%S', 'ddd': '%a'}
TOKEN_RE = re.compile('|'.join(TOKENS))


def custom_pattern(text):
    if not text.strip() or len(text) > 128 or len(text.split('\n')) > 2 or not text.split('\n')[0].strip():
        raise ValueError(_tr('格式需要一至两行，上行不能为空，最多 128 个字符。'))
    result, index = [], 0
    while index < len(text):
        match = TOKEN_RE.match(text, index)
        if match:
            result.append(TOKENS[match[0]])
            index = match.end()
        else:
            char = text[index]
            if char in '{}<>' or (char.isascii() and char.isalpha()) or (ord(char) < 32 and char != '\n'):
                raise ValueError(_tr('格式中有不支持的字符：%s') % char)
            result.append('%%' if char == '%' else char)
            index += 1
    return ''.join(result).rstrip('\n')


def styled_lines(lines):
    if len(lines) == 1: return lines[0]
    return '<span size="large" weight="bold">' + lines[0] + '</span>\n<span size="small">' + lines[1] + '</span>'


def display_pattern(prefs):
    if prefs['custom_enabled']:
        return custom_pattern(prefs['custom_format'])
    pieces = []
    if prefs['show_date']: pieces.append(date_pattern(prefs))
    if prefs['show_weekday']: pieces.append('%a')
    time = '%H:%M:%S' if prefs['show_seconds'] else '%H:%M'
    if not pieces: return time
    return time + ('\n' if prefs['two_lines'] else ' ') + ' '.join(pieces)


def definition(options, base, project_root):
    result = dict(base)
    prefs = preferences(options)
    result.pop('mnws-icon-prefix', None)
    pattern = display_pattern(prefs)
    lines = ['{0:' + html.escape(line) + '}' for line in pattern.split('\n')]
    display = styled_lines(lines)
    result.update({'format': display, 'format-alt': None, 'format-alt-click': 0,
                   'on-click-copy': False, 'menu': None,
                   'on-click-release': '', 'on-click-right-release': '',
                   'interval': 1 if '%S' in pattern.replace('%%', '') else 60,
                   'on-click': '',
                   'on-click-right': shlex.join([sys.executable, str(Path(project_root) / 'tools/mnws_clock.py'), '--launch']),
                   'actions': None, 'max-length': None, 'rotate': 0, 'justify': 'center',
                   'tooltip-format': '{:' + date_pattern(prefs) + ' %A}\n' + _tr('右键：时钟设置')})
    return result


class ClockDialog:
    def __init__(self, options, parent=None):
        import locale
        try: locale.setlocale(locale.LC_TIME, '')
        except locale.Error: pass
        from mnws_layout_gui import _gtk
        Gdk, Gtk = _gtk()
        from gi.repository import GLib
        self.Gtk, self.GLib = Gtk, GLib
        self.dialog = Gtk.Dialog(title=_tr('时钟设置'), transient_for=parent, modal=True,
                                 destroy_with_parent=True)
        self.dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        # Wayland has no X11 dialog type hint. A standalone fixed-size dialog
        # advertises equal min/max sizes, so Niri floats it from the first map.
        self.dialog.set_resizable(False)
        self.dialog.add_buttons(_tr('取消'), Gtk.ResponseType.CANCEL, _tr('确定'), Gtk.ResponseType.OK)
        self.dialog.set_default_response(Gtk.ResponseType.OK)
        self.dialog.set_default_size(420, -1)
        box = self.dialog.get_content_area()
        box.set_border_width(16)
        box.set_spacing(12)
        prefs = preferences(options)
        self.checks = {}
        for key, label in [('show_date', '显示日期'), ('show_weekday', '显示星期'), ('show_seconds', '显示秒数'), ('two_lines', '日期与时间分两行显示')]:
            check = Gtk.CheckButton(label=_tr(label))
            check.set_active(prefs[key])
            self.checks[key] = check
            box.pack_start(check, False, False, 0)
        region = time_locale()
        sample = datetime(2026, 9, 21).strftime(DATE_FORMATS[recommended_format(region)])
        hint = Gtk.Label(label=_tr('时间地区：%s\n推荐日期格式：%s') % (region, sample), xalign=0)
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label=_tr('日期格式'), xalign=0), False, False, 0)
        self.formats = Gtk.ComboBoxText()
        self.formats.append('auto', _tr('跟随地区推荐'))
        for key, pattern in DATE_FORMATS.items():
            self.formats.append(key, datetime(2026, 9, 21).strftime(pattern))
        self.formats.set_active_id(prefs['date_format'])
        self.formats.connect('scroll-event', lambda *_: True)
        row.pack_start(self.formats, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.custom_enabled = Gtk.CheckButton(label=_tr('自定义格式'))
        self.custom_enabled.set_active(prefs['custom_enabled'])
        box.pack_start(self.custom_enabled, False, False, 0)
        self.custom_entries = []
        custom_lines = prefs['custom_format'].split('\n', 1)
        for index, label in enumerate(('上行（大）', '下行（小，可留空）')):
            entry = Gtk.Entry()
            entry.set_max_length(128)
            entry.set_text(custom_lines[index] if index < len(custom_lines) else '')
            if os.environ.get('WAYLAND_DISPLAY') and os.environ.get('GDK_BACKEND') != 'x11':
                entry.set_property('im-module', 'wayland')
            row = Gtk.Box(spacing=12)
            row.pack_start(Gtk.Label(label=_tr(label), xalign=0), False, False, 0)
            row.pack_start(entry, True, True, 0)
            self.custom_entries.append(entry)
            box.pack_start(row, False, False, 0)
        legend = Gtk.Label(label=_tr('YYYY 年 · MM 月 · DD 日 · HH 时 · mm 分 · SS 秒 · ddd 星期\n例如：HH:mm:SS / YYYY-MM-DD（上下两行）'), xalign=0)
        legend.set_line_wrap(True)
        box.pack_start(legend, False, False, 0)
        self.error = Gtk.Label(xalign=0)
        self.error.set_line_wrap(True)
        box.pack_start(self.error, False, False, 0)
        self.preview = Gtk.Label(xalign=0)
        box.pack_start(self.preview, False, False, 0)
        for check in self.checks.values(): check.connect('toggled', self.refresh)
        self.formats.connect('changed', self.refresh)
        self.custom_enabled.connect('toggled', self.refresh)
        for entry in self.custom_entries: entry.connect('changed', self.refresh)
        self.timer = GLib.timeout_add_seconds(1, self.refresh)
        self.dialog.connect('destroy', self.destroyed)
        self.refresh()
        self.dialog.show_all()

    def values(self):
        return {**{key: check.get_active() for key, check in self.checks.items()},
                'date_format': self.formats.get_active_id() or 'auto',
                'custom_enabled': self.custom_enabled.get_active(),
                'custom_format': '\n'.join(entry.get_text() for entry in self.custom_entries).rstrip('\n')}

    def refresh(self, *_):
        custom = self.custom_enabled.get_active()
        for check in self.checks.values(): check.set_sensitive(not custom)
        for entry in self.custom_entries: entry.set_sensitive(custom)
        self.formats.set_sensitive(not custom and self.checks['show_date'].get_active())
        self.checks['two_lines'].set_sensitive(not custom and (self.checks['show_date'].get_active() or self.checks['show_weekday'].get_active()))
        try:
            pattern = display_pattern(self.values())
            rendered = datetime.now().strftime(pattern)
            self.preview.set_markup(styled_lines([html.escape(line) for line in rendered.split('\n')]))
            self.error.set_text('')
            self.dialog.set_response_sensitive(self.Gtk.ResponseType.OK, True)
        except ValueError as exc:
            self.error.set_markup('<span foreground="#e53935">' + html.escape(str(exc)) + '</span>')
            self.dialog.set_response_sensitive(self.Gtk.ResponseType.OK, False)
        return True

    def destroyed(self, *_):
        if self.timer:
            self.GLib.source_remove(self.timer)
            self.timer = None

    def run(self):
        return self.values() if self.dialog.run() == self.Gtk.ResponseType.OK else None


def main():
    import locale
    try: locale.setlocale(locale.LC_TIME, '')
    except locale.Error: pass
    from mnws_layout import load_layout, save_layout, apply_layout
    from mnws_theme import start
    ui = ClockDialog(load_layout().get('options', {}))
    start()
    try:
        while True:
            values = ui.run()
            if values is None: return 0
            try:
                # Reload just before saving to retain other settings changed
                # while this dialog was open.
                layout = load_layout()
                layout.setdefault('options', {})['clock'] = values
                save_layout(layout)
                ok, message = apply_layout(layout, restart=True)
                if ok: return 0
            except (OSError, ValueError) as exc:
                message = str(exc)
            error = ui.Gtk.MessageDialog(transient_for=ui.dialog, modal=True,
                                         message_type=ui.Gtk.MessageType.ERROR,
                                         buttons=ui.Gtk.ButtonsType.OK, text=_tr('应用失败'))
            error.format_secondary_text(message)
            error.run()
            error.destroy()
    finally:
        ui.dialog.destroy()


if __name__ == '__main__':
    if sys.argv[1:] == ['--launch']:
        # Waybar owns command process groups; detach so applying settings can
        # restart the bar without terminating its own settings dialog.
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                         start_new_session=True, stdin=subprocess.DEVNULL)
    else:
        raise SystemExit(main())

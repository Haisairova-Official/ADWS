"""Session-aware keyboard settings with bounded work and validated Niri writes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk
from adws_i18n import tr

TRANSLATIONS = {
    '按键重复': 'Key repeat',
    '自定义按键重复': 'Customize key repeat',
    '重复延迟': 'Repeat delay',
    '重复速度': 'Repeat rate',
    '毫秒': 'ms',
    '次 / 秒': 'keys / second',
    '按住按键时，先等待设定时间，再以设定速度重复。': 'When you hold a key, wait for the delay and then repeat at the selected rate.',
    '重复速度为 0 时关闭按键重复。': 'A repeat rate of 0 disables key repeat.',
    '当前重复参数由 Niri 配置管理；启用自定义后使用下面的数值。': 'Niri currently manages key repeat. Enable customization to use the values below.',
    '修改保存在 Niri 配置中，仅调整键盘重复，不影响鼠标、触控板和布局。': 'Saved in Niri configuration. Only keyboard repeat changes; pointing devices and layouts stay unchanged.',
    '以下设置仅在当前 Hyprland 会话生效。': 'These settings apply to the current Hyprland session.',
    '应用键盘设置': 'Apply keyboard settings',
    '键盘设置已应用。': 'Keyboard settings applied.',
    '键盘布局': 'Keyboard layout',
    '从当前会话已配置的布局中切换。': 'Switch between layouts configured in the current session.',
    '切换布局': 'Switch layout',
    '无法读取当前键盘布局。': 'Could not read the current keyboard layouts.',
    '键盘布局已切换。': 'Keyboard layout switched.',
    '键位方案': 'Modifier-key behavior',
    '轻按 Super 或 Ctrl 时的行为；组合快捷键保持原样。': 'Choose what tapping Super or Ctrl does; key combinations keep their behavior.',
    '正在检查键位方案支持…': 'Checking support for modifier-key profiles…',
    '当前 Niri 不支持单独轻按修饰键的方案。': 'This Niri version does not support modifier-key tap profiles.',
    'Super 全览 · Ctrl 无动作': 'Super: overview · Ctrl: no action',
    'Super 开始 · Ctrl 全览': 'Super: Start · Ctrl: overview',
    'Ctrl 开始 · Super 全览': 'Ctrl: Start · Super: overview',
    '当前方案：%s': 'Current profile: %s',
    '键位方案已应用。': 'Modifier-key profile applied.',
    '输入法': 'Input method',
    '配置输入法、词库、皮肤与输入法快捷键。': 'Configure input methods, dictionaries, themes, and input-method shortcuts.',
    '刷新设备状态': 'Refresh device status',
    '当前会话不支持直接配置键盘。': 'Direct keyboard configuration is unavailable in this session.',
    '正在读取键盘设置…': 'Reading keyboard settings…',
    '无法读取键盘设置：%s': 'Could not read keyboard settings: %s',
    '键盘重复数值超出允许范围。': 'Keyboard repeat values are outside the allowed range.',
    'ADWS 输入配置标记不完整，请检查 Niri 配置。': 'The ADWS input configuration markers are incomplete. Check Niri configuration.',
    'ADWS 输入配置文件不完整，请检查 Niri 配置。': 'The ADWS input configuration is incomplete. Check Niri configuration.',
    '未找到 Niri，无法校验键盘设置。': 'Niri is unavailable; keyboard settings cannot be validated.',
    '输入配置发生冲突，未修改配置。': 'Input configuration conflict; nothing was changed.',
    'Niri 校验失败，未修改键盘设置：%s': 'Niri validation failed; keyboard settings were not changed: %s',
    'Niri 配置已被其他程序修改，请刷新后重试。': 'Another application changed Niri configuration. Refresh and try again.',
    '布局已变更，请刷新后重试。': 'The available layouts changed. Refresh and try again.',
}

BEGIN = '// ==== ADWS input settings BEGIN ===='
END = '// ==== ADWS input settings END ===='
BLOCK = re.compile(r'(?m)^' + re.escape(BEGIN) + r'\ninclude "(\.adws-input-[a-f0-9]{20}\.kdl)"\n' + re.escape(END) + r'\n?')


def run(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=5)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[:1500])
    return result.stdout


def validated_values(rate, delay):
    if type(rate) is not int or type(delay) is not int or not 0 <= rate <= 255 or not 100 <= delay <= 5000:
        raise ValueError(tr('键盘重复数值超出允许范围。'))
    return {'rate': rate, 'delay': delay}


def clean_block(text):
    matches = list(BLOCK.finditer(text))
    if text.count(BEGIN) != len(matches) or text.count(END) != len(matches) or len(matches) > 1:
        raise ValueError(tr('ADWS 输入配置标记不完整，请检查 Niri 配置。'))
    return BLOCK.sub('', text)


def input_content(values):
    value = validated_values(values['rate'], values['delay'])
    return ('// ADWS keyboard repeat; other input settings are unchanged.\n'
            '// values: ' + json.dumps(value, sort_keys=True) + '\n'
            'input {\n    keyboard {\n'
            f'        repeat-delay {value["delay"]}\n'
            f'        repeat-rate {value["rate"]}\n'
            '    }\n}\n')


def read_niri_repeat(path=None):
    from adws_windows import config_path
    path = (Path(path) if path is not None else config_path()).resolve()
    text = path.read_text()
    clean_block(text)
    match = BLOCK.search(text)
    if not match:
        return None
    content = (path.parent / match[1]).read_text()
    metadata = re.search(r'(?m)^// values: (.+)$', content)
    if not metadata:
        raise ValueError(tr('ADWS 输入配置文件不完整，请检查 Niri 配置。'))
    value = json.loads(metadata[1])
    value = validated_values(value['rate'], value['delay'])
    if content != input_content(value):
        raise ValueError(tr('ADWS 输入配置文件不完整，请检查 Niri 配置。'))
    return value


def apply_niri_repeat(enabled, values, path=None):
    """Validate the whole config before atomically replacing one managed include.

    Niri merges keyboard repeat fields across includes, while pointing-device
    subtrees replace as a whole. This include therefore never emits mouse,
    touchpad or XKB nodes.
    """
    from adws_windows import config_path
    from adws_niri_compat import niri_binary
    from adws_atomic import replace_files
    values = validated_values(values['rate'], values['delay'])
    path = (Path(path) if path is not None else config_path()).resolve()
    niri = niri_binary()
    if not niri:
        raise ValueError(tr('未找到 Niri，无法校验键盘设置。'))
    old = path.read_text()
    clean = clean_block(old)
    included = None
    created = committed = False
    temporary = None
    try:
        updated = clean
        if enabled:
            content = input_content(values)
            digest = hashlib.sha256(content.encode()).hexdigest()[:20]
            included = path.parent / ('.adws-input-' + digest + '.kdl')
            if included.exists():
                if included.read_text() != content:
                    raise ValueError(tr('输入配置发生冲突，未修改配置。'))
            else:
                with included.open('x') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                created = True
            updated = clean.rstrip() + '\n\n' + BEGIN + '\ninclude ' + json.dumps(included.name) + '\n' + END + '\n'
        if updated == old:
            committed = True
            return
        with tempfile.NamedTemporaryFile(mode='w', suffix='.kdl', prefix='.adws-input-check-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
        result = subprocess.run([niri, 'validate', '-c', str(temporary)], text=True, capture_output=True, timeout=5)
        if result.returncode:
            raise ValueError(tr('Niri 校验失败，未修改键盘设置：%s') % (result.stderr or result.stdout).strip()[:1500])
        if path.read_text() != old:
            raise ValueError(tr('Niri 配置已被其他程序修改，请刷新后重试。'))
        shutil.copy2(path, path.with_suffix(path.suffix + '.adws-input-bak'))
        replace_files({path: updated.encode()})
        committed = True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if included is not None and created and not committed:
            included.unlink(missing_ok=True)


def read_hyprland_repeat():
    values = {}
    for key, option in (('rate', 'repeat_rate'), ('delay', 'repeat_delay')):
        value = json.loads(run(['hyprctl', '-j', 'getoption', 'input:' + option]))
        if type(value.get('int')) is not int:
            raise ValueError('Hyprland did not return an integer ' + option)
        values[key] = value['int']
    return validated_values(values['rate'], values['delay'])


def apply_hyprland_repeat(values):
    values = validated_values(values['rate'], values['delay'])
    previous = read_hyprland_repeat()
    touched = []
    try:
        for key, option in (('rate', 'repeat_rate'), ('delay', 'repeat_delay')):
            touched.append((key, option))
            reply = run(['hyprctl', 'keyword', 'input:' + option, str(values[key])])
            if reply.strip().casefold() != 'ok':
                raise RuntimeError(reply.strip())
    except Exception as error:
        failures = []
        for key, option in reversed(touched):
            try:
                reply = run(['hyprctl', 'keyword', 'input:' + option, str(previous[key])])
                if reply.strip().casefold() != 'ok':
                    raise RuntimeError(reply.strip())
            except Exception as restore_error:
                failures.append(str(restore_error))
        if failures:
            raise RuntimeError(f'{error}; restore failed: ' + '; '.join(failures)) from error
        raise


def niri_layouts():
    value = json.loads(run(['niri', 'msg', '--json', 'keyboard-layouts']))
    names, index = value.get('names'), value.get('current_idx')
    if not isinstance(names, list) or not names or not all(isinstance(name, str) for name in names) or type(index) is not int or not 0 <= index < len(names):
        raise ValueError(tr('无法读取当前键盘布局。'))
    return value


def switch_niri_layout(index, expected_names):
    if type(index) is not int or not 0 <= index < len(expected_names):
        raise ValueError(tr('布局已变更，请刷新后重试。'))
    if niri_layouts()['names'] != expected_names:
        raise ValueError(tr('布局已变更，请刷新后重试。'))
    run(['niri', 'msg', 'action', 'switch-layout', str(index)])


class InputSettingsPage(Gtk.Box):
    def __init__(self, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        from adws_display import detect_session
        from adws_system_settings import card, label
        from adws_settings_widgets import compact_switch, settings_tabs
        self.host, self.session = host, detect_session()
        self.loading, self.alive, self.generation = True, True, 0
        self.layout_names = []
        self.connect('destroy', lambda *_: setattr(self, 'alive', False))
        toolbar = Gtk.Box(spacing=12)
        self.status = label('正在读取键盘设置…', 'dim-label')
        toolbar.pack_start(self.status, True, True, 0)
        refresh = Gtk.Button(label=tr('刷新设备状态'))
        refresh.set_valign(Gtk.Align.CENTER)
        refresh.connect('clicked', self.refresh)
        toolbar.pack_end(refresh, False, False, 0)
        self.pack_start(toolbar, False, False, 0)
        keyboard, shortcuts, methods = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18) for _ in range(3)]
        self.tabs = settings_tabs([('keyboard',tr('键盘'),keyboard),('shortcuts',tr('快捷键'),shortcuts),('methods',tr('输入法'),methods)])
        self.pack_start(self.tabs, False, False, 0)
        if self.session == 'niri':
            layout_card = card('键盘布局', '从当前会话已配置的布局中切换。')
            self.layouts = Gtk.ComboBoxText()
            self.layout_button = Gtk.Button(label=tr('切换布局'))
            self.layout_button.connect('clicked', self.switch_layout)
            self.layout_button.set_sensitive(False)
            line = Gtk.Box(spacing=12)
            line.pack_start(self.layouts, True, True, 0)
            line.pack_end(self.layout_button, False, False, 0)
            layout_card.pack_start(line, False, False, 0)
            keyboard.pack_start(layout_card, False, False, 0)
        self.repeat_card = card('按键重复', '按住按键时，先等待设定时间，再以设定速度重复。')
        keyboard.pack_start(self.repeat_card, False, False, 0)
        self.custom = compact_switch(Gtk.Switch())
        self._row(self.repeat_card, '自定义按键重复', self.custom)
        self.delay = Gtk.SpinButton.new_with_range(100, 5000, 50)
        self.rate = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.delay.set_value(600); self.rate.set_value(25)
        self._row(self.repeat_card, '重复延迟', self.delay, '毫秒')
        self._row(self.repeat_card, '重复速度', self.rate, '次 / 秒')
        self.repeat_hint = label('重复速度为 0 时关闭按键重复。', 'dim-label')
        self.repeat_card.pack_start(self.repeat_hint, False, False, 0)
        test = Gtk.Entry()
        test.set_placeholder_text(tr('在这里按住按键，测试重复速度…'))
        test.set_max_length(512)
        self.repeat_card.pack_start(test, False, False, 0)
        note = ('修改保存在 Niri 配置中，仅调整键盘重复，不影响鼠标、触控板和布局。' if self.session == 'niri' else '以下设置仅在当前 Hyprland 会话生效。')
        self.repeat_card.pack_start(label(note, 'dim-label'), False, False, 0)
        self.apply_button = Gtk.Button(label=tr('应用键盘设置'))
        self.apply_button.set_halign(Gtk.Align.END)
        self.apply_button.get_style_context().add_class('suggested-action')
        self.apply_button.connect('clicked', self.apply_changes)
        self.repeat_card.pack_start(self.apply_button, False, False, 0)
        self.custom.connect('notify::active', self.changed)
        self.rate.connect('value-changed', self.changed)
        self.delay.connect('value-changed', self.changed)
        self.repeat_card.set_sensitive(False)
        if self.session == 'niri':
            profile_card = card('键位方案', '轻按 Super 或 Ctrl 时的行为；组合快捷键保持原样。')
            self.profile_hint = label('正在检查键位方案支持…', 'dim-label')
            profile_card.pack_start(self.profile_hint, False, False, 0)
            self.profile_buttons = []
            for key, title, subtitle in [('waylander','Waylander','Super 全览 · Ctrl 无动作'), ('traditional','Traditional','Super 开始 · Ctrl 全览'), ('reversed','Reversed','Ctrl 开始 · Super 全览')]:
                control = Gtk.Button()
                control.get_style_context().add_class('settings-profile-choice')
                control.set_sensitive(False)
                inner = Gtk.Box(spacing=18)
                title_label = label(title, 'settings-section-title')
                title_label.set_width_chars(12)
                inner.pack_start(title_label, False, False, 0)
                inner.pack_start(label(subtitle, 'dim-label'), True, True, 0)
                marker = Gtk.Image.new_from_icon_name('object-select-symbolic', Gtk.IconSize.MENU)
                marker.set_no_show_all(True)
                inner.pack_end(marker, False, False, 0)
                control.profile_marker = marker
                control.add(inner)
                control.connect('clicked', lambda _, value=key: self.apply_profile(value))
                profile_card.pack_start(control, False, False, 0)
                self.profile_buttons.append((key, control))
            shortcuts.pack_start(profile_card, False, False, 0)
        else:
            shortcuts.pack_start(card('快捷键','当前会话不支持单独轻按修饰键的方案。'),False,False,0)
        from adws_native_input import input_sections
        input_sections(self.host, methods)
        self.refresh()

    def _row(self, box, title, control, unit=None):
        from adws_native_settings_gui import row
        from adws_system_settings import label
        if unit:
            controls = Gtk.Box(spacing=10)
            controls.pack_start(control,False,False,0)
            controls.pack_end(label(unit,'dim-label'),False,False,0)
            control = controls
        row(box,title,control)

    def refresh(self, *_):
        if 'input' in self.host.dirty:
            if not self.host.confirm('放弃尚未应用的修改？', '已应用的设置会保留。'):
                return
        self.generation += 1
        generation = self.generation
        self.loading = True
        self.repeat_card.set_sensitive(False)
        self.status.set_text(tr('正在读取键盘设置…'))
        def worker():
            data = {}
            try:
                if self.session == 'niri':
                    data['repeat'] = read_niri_repeat()
                elif self.session == 'hyprland':
                    data['repeat'] = read_hyprland_repeat()
                else:
                    raise ValueError(tr('当前会话不支持直接配置键盘。'))
            except Exception as exc:
                data['error'] = str(exc)
            if self.session == 'niri':
                from adws_keyboard import modifier_taps_supported, current_profile
                try:
                    data['layouts'] = niri_layouts()
                except Exception:
                    data['layouts'] = None
                try:
                    data['profile_supported'] = modifier_taps_supported()
                    data['profile'] = current_profile()
                except Exception:
                    data['profile_supported'] = False
            GLib.idle_add(finish, data)
        def finish(data):
            if not self.alive or generation != self.generation:
                return False
            if 'error' in data:
                self.status.set_text(tr('无法读取键盘设置：%s') % data['error'])
            else:
                values = data['repeat']
                self.custom.set_active(values is not None)
                self.custom.set_sensitive(self.session == 'niri')
                self.rate.set_value(values['rate'] if values else 25)
                self.delay.set_value(values['delay'] if values else 600)
                self.repeat_card.set_sensitive(True)
                self.status.set_text(tr('当前重复参数由 Niri 配置管理；启用自定义后使用下面的数值。') if values is None else '')
            if self.session == 'niri':
                self.layouts.remove_all()
                layout = data.get('layouts')
                self.layout_names = layout['names'] if layout else []
                for i, name in enumerate(self.layout_names):
                    self.layouts.append(str(i), name)
                self.layouts.set_active(layout['current_idx'] if layout else -1)
                self.layout_button.set_sensitive(bool(layout))
                if not layout:
                    self.layouts.set_tooltip_text(tr('无法读取当前键盘布局。'))
                supported = data.get('profile_supported', False)
                self.profile_hint.set_text(tr('当前方案：%s') % data.get('profile', '') if supported else tr('当前 Niri 不支持单独轻按修饰键的方案。'))
                for key, button in self.profile_buttons:
                    button.set_sensitive(supported)
                    context = button.get_style_context()
                    (context.add_class if data.get('profile') == key else context.remove_class)('selected-profile')
                    button.profile_marker.set_visible(data.get('profile') == key)
            self.loading = False
            self.host.dirty.discard('input')
            self.host.update_footer()
            self._sensitivity()
            return False
        threading.Thread(target=worker, daemon=True).start()

    def _sensitivity(self):
        enabled = self.custom.get_active()
        self.rate.set_sensitive(enabled)
        self.delay.set_sensitive(enabled)
        self.apply_button.set_sensitive('input' in self.host.dirty)

    def changed(self, *_):
        if not self.loading:
            self.host.mark_dirty('input')
        self._sensitivity()

    def apply_changes(self, *_, after=None):
        if self.loading or not self.repeat_card.get_sensitive():
            return
        values = validated_values(self.rate.get_value_as_int(), self.delay.get_value_as_int())
        enabled = self.custom.get_active()
        job = (lambda: apply_niri_repeat(enabled, values)) if self.session == 'niri' else (lambda: apply_hyprland_repeat(values))
        def complete():
            self.host.dirty.discard('input')
            self.status.set_text(tr('键盘设置已应用。'))
            self._sensitivity()
            if after:
                after()
        self.host.run_worker(job, complete)

    def switch_layout(self, *_):
        index = self.layouts.get_active()
        names = list(self.layout_names)
        self.host.run_worker(lambda: switch_niri_layout(index, names), lambda: self.status.set_text(tr('键盘布局已切换。')))

    def apply_profile(self, profile):
        from adws_keyboard import apply_profile
        def complete():
            self.status.set_text(tr('键位方案已应用。'))
            self.profile_hint.set_text(tr('当前方案：%s') % profile)
            for key, button in self.profile_buttons:
                context = button.get_style_context()
                (context.add_class if key == profile else context.remove_class)('selected-profile')
                button.profile_marker.set_visible(key == profile)
        self.host.run_worker(lambda: apply_profile(profile), complete)

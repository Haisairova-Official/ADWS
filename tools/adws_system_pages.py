"""Optional desktop services for ADWS settings.

The adapters deliberately import no GTK.  Discovery is bounded and read-only;
changes are made only by an explicit page action.  Installed services remain the
owners of their configuration (NetworkManager, BlueZ, PulseAudio/PipeWire, PPD).
"""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import threading
import uuid
import xml.etree.ElementTree as ET


TRANSLATIONS = {
    '网络与连接': 'Network & connections',
    '查看网络设备，连接已保存的网络并管理 Wi-Fi。': 'View network devices, connect to saved networks and manage Wi-Fi.',
    '蓝牙': 'Bluetooth',
    '管理蓝牙电源、耳机和其他已配对设备。': 'Manage Bluetooth power, headphones and other paired devices.',
    '声音': 'Sound',
    '选择输入输出设备，调整音量与静音。': 'Choose input and output devices, volume and mute.',
    '电源与电池': 'Power & battery',
    '查看电池状态，选择系统支持的电源模式。': 'Check battery status and choose a supported power profile.',
    '账户与地区': 'Account & region',
    '账户、语言、地区格式与输入法。': 'Account, language, regional formats and input methods.',
    '设备与连接': 'Devices & connections',
    '系统': 'System',
    '正在读取系统状态…': 'Reading system status…',
    '刷新状态': 'Refresh status',
    '重新读取': 'Read again',
    '设置已更新。': 'Settings updated.',
    '无法读取系统状态：%s': 'Could not read system status: %s',
    '未安装 %s。': '%s is not installed.',
    '没有可用的系统服务。': 'No supported system service is available.',
    '此页面直接使用系统服务；操作后立即生效。': 'This page uses system services directly. Actions take effect immediately.',
    '高级设置': 'Advanced settings',
    '网络设备': 'Network devices',
    '已保存的连接': 'Saved connections',
    '没有已保存的网络连接。': 'No saved network connections.',
    '未检测到网络设备。': 'No network devices detected.',
    '已连接': 'Connected',
    '未连接': 'Disconnected',
    '连接中': 'Connecting',
    '不可用': 'Unavailable',
    '未托管': 'Unmanaged',
    '未知': 'Unknown',
    'Wi-Fi': 'Wi-Fi',
    '开启 Wi-Fi': 'Enable Wi-Fi',
    '关闭 Wi-Fi': 'Disable Wi-Fi',
    '已开启': 'On',
    '已关闭': 'Off',
    '有线网络': 'Ethernet',
    '虚拟网络': 'Virtual network',
    '连接': 'Connect',
    '断开': 'Disconnect',
    '断开此网络连接？': 'Disconnect this network?',
    '使用此连接的应用可能暂时无法访问网络。': 'Applications using this connection may temporarily lose network access.',
    '关闭 Wi-Fi？': 'Disable Wi-Fi?',
    '当前的无线网络连接将会断开。': 'The current wireless connection will be disconnected.',
    '需要 NetworkManager 与 nmcli 才能在此管理网络。': 'NetworkManager and nmcli are required to manage networks here.',
    '蓝牙适配器': 'Bluetooth adapter',
    '开启蓝牙': 'Enable Bluetooth',
    '关闭蓝牙': 'Disable Bluetooth',
    '关闭蓝牙？': 'Disable Bluetooth?',
    '已连接的蓝牙键盘、鼠标和耳机将会断开。': 'Connected Bluetooth keyboards, mice and headphones will be disconnected.',
    '已配对的设备': 'Paired devices',
    '没有已配对的设备。': 'No paired devices.',
    '未检测到蓝牙适配器。': 'No Bluetooth adapter detected.',
    '需要 BlueZ 与 bluetoothctl 才能在此管理蓝牙。': 'BlueZ and bluetoothctl are required to manage Bluetooth here.',
    '输出设备': 'Output devices',
    '输入设备': 'Input devices',
    '未检测到声音输出设备。': 'No audio output devices detected.',
    '未检测到麦克风。': 'No microphones detected.',
    '默认设备': 'Default device',
    '设为默认': 'Set as default',
    '已静音': 'Muted',
    '未静音': 'Unmuted',
    '取消静音': 'Unmute',
    '静音': 'Mute',
    '音量': 'Volume',
    '应用音量': 'Apply volume',
    '应用音量、声道与设备配置…': 'Application volume, channels & device profiles…',
    '需要 pactl 及 PulseAudio 或 PipeWire Pulse 服务。': 'Requires pactl and a PulseAudio or PipeWire Pulse service.',
    '设备音量高于 100%；滑块显示上限为 100%，点击应用才会调整。': 'Device volume is above 100%. The slider is capped at 100% and changes only when you apply it.',
    '电池': 'Battery',
    '未检测到电池。': 'No battery detected.',
    '正在充电': 'Charging',
    '正在放电': 'Discharging',
    '已充满': 'Fully charged',
    '未充电': 'Not charging',
    '电源模式': 'Power profile',
    '省电': 'Power saver',
    '平衡': 'Balanced',
    '性能': 'Performance',
    '优先延长续航并降低功耗。': 'Prioritize battery life and lower power consumption.',
    '在性能与功耗之间取得平衡。': 'Balance performance and power consumption.',
    '优先提高性能，可能增加功耗和风扇噪音。': 'Prioritize performance, potentially increasing power use and fan noise.',
    '当前模式': 'Current profile',
    '使用此模式': 'Use this profile',
    '系统未提供可切换的电源模式。': 'The system does not provide switchable power profiles.',
    '需要 power-profiles-daemon 才能在此切换电源模式。': 'Power Profiles Daemon is required to switch profiles here.',
    '当前账户': 'Current account',
    '用户名': 'Username',
    '显示名称': 'Display name',
    '语言与地区': 'Language & region',
    '界面语言': 'Interface language',
    '日期格式': 'Date format',
    '数字格式': 'Number format',
    '当前会话': 'Current session',
    '账户管理…': 'Manage accounts…',
    '语言与地区设置…': 'Language & region settings…',
    '输入法设置…': 'Input method settings…',
    '更改系统语言通常需要重新登录才能对所有应用生效。': 'Changes to the system language usually require signing in again to affect all applications.',
    '系统未安装受支持的账户或地区配置工具。': 'No supported account or regional configuration tool is installed.',
    '系统操作失败。': 'The system operation failed.',
    '系统服务没有响应，请稍后重试。': 'The system service did not respond. Try again later.',
    '该功能所需的软件已被移除。': 'The software required for this action has been removed.',
    '应用账户设置': 'Apply account settings',
    '地区格式（日期与数字）': 'Regional formats (dates & numbers)',
    '系统没有提供可直接编辑的账户服务。': 'The system does not provide an account service for direct editing.',
    '没有读取到可用的系统语言。': 'No available system locales could be read.',
    '更改将在重新登录后生效。': 'Changes take effect after signing in again.',
    '账户设置由系统服务保存；语言更改在重新登录后生效。': 'Account settings are saved by the system service. Language changes take effect after signing in again.',
    '账户信息已被其他程序修改，请刷新后重试。': 'Another application changed this account. Refresh and try again.',
    '只能修改当前登录用户的账户。': 'Only the currently signed-in user can be edited.',
    '系统不支持修改此账户设置。': 'The system does not support changing this account setting.',
    '请选择系统中已安装的语言。': 'Choose a locale installed on this system.',
    '显示名称不能为空、超过 128 个字符或包含控制字符。': 'The display name must contain 1–128 characters and no control characters.',
    '账户设置失败，先前的设置已恢复。': 'Account settings failed; previous settings have been restored.',
    '账户设置未完全应用，恢复也未完成：%s': 'Account settings were only partly applied and could not be fully restored: %s',
    '放弃尚未应用的账户修改？': 'Discard unapplied account changes?',
    '刷新会重新读取系统中的账户设置。': 'Refreshing reads the account settings stored by the system again.',
}


def _tr(text):
    from adws_i18n import tr
    return tr(text)


def available_pages():
    """Navigation records in the same order as the system-settings Page model."""
    return [
        ('network', '网络与连接', '查看网络设备，连接已保存的网络并管理 Wi-Fi。',
         'network-wireless-symbolic', '设备与连接', 'network wifi ethernet vpn 网络 无线 连接 代理'),
        ('bluetooth', '蓝牙', '管理蓝牙电源、耳机和其他已配对设备。',
         'bluetooth-symbolic', '设备与连接', 'bluetooth headphones pairing 蓝牙 耳机 配对'),
        ('sound', '声音', '选择输入输出设备，调整音量与静音。',
         'audio-volume-high-symbolic', '设备与连接', 'sound audio volume microphone speaker 声音 音量 麦克风 扬声器'),
        ('power', '电源与电池', '查看电池状态，选择系统支持的电源模式。',
         'battery-symbolic', '系统', 'power battery performance sleep energy 电源 电池 节能 性能 睡眠'),
        ('region', '账户与地区', '账户、语言、地区格式与输入法。',
         'preferences-desktop-locale-symbolic', '系统', 'user account language region locale input 用户 账户 地区 语言 输入法'),
    ]


def command(args, timeout=4):
    """Run a bounded non-interactive request; never use a shell or alter locale."""
    env = dict(os.environ, LC_ALL='C', LANG='C', LANGUAGE='C', NO_COLOR='1')
    try:
        process = subprocess.run(list(args), capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=timeout,
                                 check=False, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(_tr('系统服务没有响应，请稍后重试。')) from exc
    except FileNotFoundError as exc:
        raise RuntimeError(_tr('未安装 %s。') % args[0]) from exc
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()
        raise RuntimeError(detail[:1000] or _tr('系统操作失败。'))
    return process.stdout


def terse_rows(text, count):
    """Decode nmcli's escaped colon-separated columns, including backslashes."""
    rows = []
    for line in text.splitlines():
        fields, token, escaped = [], [], False
        for char in line:
            if escaped:
                token.append(char)
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == ':':
                fields.append(''.join(token)); token = []
            else:
                token.append(char)
        if escaped:
            token.append('\\')
        fields.append(''.join(token))
        if len(fields) == count:
            rows.append(fields)
    return rows


def network_snapshot():
    if not shutil.which('nmcli'):
        return {'missing': '需要 NetworkManager 与 nmcli 才能在此管理网络。'}
    radio = command(['nmcli', '-t', '-f', 'WIFI', 'general', 'status']).strip()
    devices = terse_rows(command(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status']), 4)
    profiles = terse_rows(command(['nmcli', '-t', '-f', 'UUID,NAME,TYPE,DEVICE', 'connection', 'show']), 4)
    return {'wifi': radio == 'enabled', 'devices': devices, 'connections': profiles}


def wifi_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError('Wi-Fi state must be a boolean')
    command(['nmcli', '--wait', '8', 'radio', 'wifi', 'on' if enabled else 'off'], timeout=10)


def network_connection(connection_uuid, enabled):
    # UUIDs, not names supplied by the network, select connections unambiguously.
    identity = str(uuid.UUID(connection_uuid))
    if type(enabled) is not bool:
        raise ValueError('Connection state must be a boolean')
    command(['nmcli', '--wait', '15', 'connection', 'up' if enabled else 'down', 'uuid', identity], timeout=17)


_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
_MAC = re.compile(r'[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}')


def bluetooth_command(*args, timeout=4):
    # bluetoothctl --timeout keeps even read-only one-shot commands alive for
    # that whole duration. The subprocess deadline is sufficient and immediate.
    result = _ANSI.sub('', command(['bluetoothctl', *args], timeout=timeout))
    # BlueZ sometimes reports a failed D-Bus action while exiting successfully.
    if re.search(r'(?im)^\s*(?:Failed\b|No default controller|Device .* not available|org\.bluez\.Error)', result):
        raise RuntimeError(result.strip()[:1000])
    return result


def bluetooth_devices(text):
    result = {}
    for line in text.splitlines():
        match = re.match(r'^Device ([0-9A-Fa-f:]{17}) (.*)$', line.strip())
        if match and _MAC.fullmatch(match[1]):
            result[match[1].upper()] = match[2]
    return result


def bluetooth_snapshot():
    if not shutil.which('bluetoothctl'):
        return {'missing': '需要 BlueZ 与 bluetoothctl 才能在此管理蓝牙。'}
    controllers = bluetooth_command('list').strip()
    if not controllers:
        return {'adapter': None, 'devices': []}
    text = bluetooth_command('show')
    adapter = re.search(r'^\s*Alias: (.+)$', text, re.M)
    powered = bool(re.search(r'^\s*Powered: yes\s*$', text, re.M))
    paired = bluetooth_devices(bluetooth_command('devices', 'Paired'))
    connected = bluetooth_devices(bluetooth_command('devices', 'Connected'))
    return {'adapter': adapter[1] if adapter else 'Bluetooth', 'powered': powered,
            'devices': [{'address': address, 'name': name, 'connected': address in connected}
                        for address, name in sorted(paired.items(), key=lambda pair: (pair[0] not in connected, pair[1].casefold()))]}


def bluetooth_power(enabled):
    if type(enabled) is not bool:
        raise ValueError('Bluetooth power must be a boolean')
    bluetooth_command('power', 'on' if enabled else 'off', timeout=8)


def bluetooth_connect(address, connected):
    if not isinstance(address, str) or not _MAC.fullmatch(address) or type(connected) is not bool:
        raise ValueError('Invalid Bluetooth action')
    bluetooth_command('connect' if connected else 'disconnect', address.upper(), timeout=8)


def audio_devices(raw, kind, default):
    devices = []
    if not isinstance(raw, list):
        raise ValueError('Invalid audio service response')
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get('index'), int):
            continue
        if kind == 'source' and (item.get('monitor_of_sink') not in (None, 4294967295, '')
                                 or str(item.get('name', '')).endswith('.monitor')):
            continue
        channels = item.get('volume') or {}
        values = [float(value.get('value', 0)) / 65536 * 100
                  for value in channels.values() if isinstance(value, dict)]
        volume = max(values, default=0)
        if not math.isfinite(volume):
            volume = 0
        devices.append({'index': item['index'], 'name': str(item.get('name', '')),
                        'description': str(item.get('description') or item.get('name', '')),
                        'default': item.get('name') == default, 'mute': bool(item.get('mute')),
                        'volume': max(0, round(volume)), 'kind': kind})
    return devices


def audio_snapshot():
    if not shutil.which('pactl'):
        return {'missing': '需要 pactl 及 PulseAudio 或 PipeWire Pulse 服务。'}
    # Separate connections are concurrent but bounded. Opening the page never
    # leaves subscriptions or polling processes running after it is closed.
    requests = (['pactl', '-f', 'json', 'list', 'sinks'],
                ['pactl', '-f', 'json', 'list', 'sources'],
                ['pactl', 'get-default-sink'], ['pactl', 'get-default-source'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        sinks, sources, default_sink, default_source = list(pool.map(command, requests))
    return {'sinks': audio_devices(json.loads(sinks), 'sink', default_sink.strip()),
            'sources': audio_devices(json.loads(sources), 'source', default_source.strip())}


def audio_change(kind, index, action, value=None):
    if kind not in ('sink', 'source') or type(index) is not int or index < 0:
        raise ValueError('Invalid audio device')
    if action == 'default' and isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:@+-]*', value):
        # The default-device API takes the stable PulseAudio name, not an index.
        args = ['set-default-' + kind, value]
    elif action == 'mute' and type(value) is bool:
        args = ['set-' + kind + '-mute', str(index), '1' if value else '0']
    elif action == 'volume' and type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100:
        args = ['set-' + kind + '-volume', str(index), f'{round(value)}%']
    else:
        raise ValueError('Invalid audio action')
    command(['pactl', *args])


POWER_PROFILES = ('power-saver', 'balanced', 'performance')


def parse_power_profiles(text):
    return [match[1] for line in text.splitlines()
            if (match := re.fullmatch(r'\s*\*?\s*(power-saver|balanced|performance):\s*', line))]


def batteries(root=Path('/sys/class/power_supply')):
    result = []
    try:
        paths = sorted(root.iterdir())
    except OSError:
        return result
    for path in paths:
        try:
            if (path / 'type').read_text().strip() != 'Battery':
                continue
            capacity = int((path / 'capacity').read_text().strip())
            status = (path / 'status').read_text().strip()
            result.append({'name': path.name, 'capacity': max(0, min(100, capacity)), 'status': status})
        except (OSError, ValueError):
            continue
    return result


def power_snapshot():
    result = {'batteries': batteries(), 'profiles': [], 'active': ''}
    if shutil.which('powerprofilesctl'):
        try:
            result['profiles'] = parse_power_profiles(command(['powerprofilesctl', 'list']))
            result['active'] = command(['powerprofilesctl', 'get']).strip()
        except RuntimeError as exc:
            result['profile_error'] = str(exc)
    else:
        result['profile_error'] = _tr('需要 power-profiles-daemon 才能在此切换电源模式。')
    return result


def power_profile(profile):
    if profile not in POWER_PROFILES:
        raise ValueError('Invalid power profile')
    command(['powerprofilesctl', 'set', profile])


ACCOUNT_SERVICE = 'org.freedesktop.Accounts'
ACCOUNT_INTERFACE = 'org.freedesktop.Accounts.User'
ACCOUNT_FIELDS = {'name': ('RealName', 'SetRealName'), 'language': ('Language', 'SetLanguage'),
                  'formats': ('FormatsLocale', 'SetFormatsLocale')}


def account_path():
    # The UI never supplies an object path or a target user.
    return '/org/freedesktop/Accounts/User' + str(os.getuid())


def account_snapshot():
    if not shutil.which('busctl'):
        return None
    base = ['busctl', '--system', '--no-pager', '--timeout=3']
    raw = json.loads(command([*base, '--json=short', '--', 'call', ACCOUNT_SERVICE, account_path(),
                              'org.freedesktop.DBus.Properties', 'GetAll', 's', ACCOUNT_INTERFACE]))
    props = raw.get('data', [None])[0]
    if raw.get('type') != 'a{sv}' or not isinstance(props, dict):
        raise ValueError('Invalid account-service response')
    uid = props.get('Uid', {}).get('data')
    if type(uid) is not int or uid != os.getuid():
        raise RuntimeError(_tr('只能修改当前登录用户的账户。'))
    xml = command([*base, '--xml-interface', '--', 'introspect', ACCOUNT_SERVICE,
                   account_path(), ACCOUNT_INTERFACE])
    root = ET.fromstring(xml)
    methods = set()
    for interface in root.findall('interface'):
        if interface.get('name') != ACCOUNT_INTERFACE:
            continue
        for method in interface.findall('method'):
            inputs = [arg.get('type') for arg in method.findall('arg') if arg.get('direction', 'in') == 'in']
            if inputs == ['s']:
                methods.add(method.get('name'))
    icon = props.get('IconFile', {})
    result = {'uid': uid, 'supported': [], 'name': '', 'language': '', 'formats': '',
              'avatar': icon.get('data') if icon.get('type') == 's' and isinstance(icon.get('data'), str) else None}
    for field, (prop, method) in ACCOUNT_FIELDS.items():
        value = props.get(prop, {})
        if value.get('type') == 's' and isinstance(value.get('data'), str):
            result[field] = value['data']
            if method in methods:
                result['supported'].append(field)
    return result


def available_locales():
    values = command(['locale', '-a']).splitlines()
    # "C" is a supported locale too; do not invent locales absent from libc.
    return sorted({value.strip() for value in values if re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}', value.strip())},
                  key=str.casefold)


def locale_key(value):
    return value.casefold().replace('utf-8', 'utf8')


def locale_title(value):
    language = re.split(r'[_.@-]', value)[0].casefold()
    native = {'en': 'English', 'zh': '中文', 'ja': '日本語', 'ko': '한국어', 'de': 'Deutsch',
              'fr': 'Français', 'es': 'Español', 'pt': 'Português', 'ru': 'Русский',
              'it': 'Italiano', 'uk': 'Українська', 'ar': 'العربية', 'nl': 'Nederlands',
              'pl': 'Polski', 'tr': 'Türkçe', 'sv': 'Svenska', 'fi': 'Suomi'}.get(language)
    return f'{native} · {value}' if native else value


def set_account_field(field, value):
    method = ACCOUNT_FIELDS[field][1]
    # Polkit can present an authentication dialog. A leading '--' prevents a
    # real name beginning with '-' from ever being parsed as a busctl option.
    command(['busctl', '--system', '--no-pager', '--timeout=60',
             '--allow-interactive-authorization=yes', '--', 'call', ACCOUNT_SERVICE,
             account_path(), ACCOUNT_INTERFACE, method, 's', value], timeout=65)


def apply_account(expected, changes):
    if not isinstance(expected, dict) or expected.get('uid') != os.getuid():
        raise RuntimeError(_tr('只能修改当前登录用户的账户。'))
    if not isinstance(changes, dict) or set(changes) - set(ACCOUNT_FIELDS):
        raise ValueError('Invalid account fields')
    locales = None
    for field, value in changes.items():
        if field not in expected.get('supported', ()):
            raise RuntimeError(_tr('系统不支持修改此账户设置。'))
        if field == 'name':
            if not isinstance(value, str) or not value.strip() or len(value) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError(_tr('显示名称不能为空、超过 128 个字符或包含控制字符。'))
        else:
            if locales is None:
                locales = {locale_key(item) for item in available_locales()}
            if not isinstance(value, str) or locale_key(value) not in locales:
                raise ValueError(_tr('请选择系统中已安装的语言。'))
    current = account_snapshot()
    if current is None or current['uid'] != os.getuid():
        raise RuntimeError(_tr('只能修改当前登录用户的账户。'))
    for field in changes:
        if field not in current['supported']:
            raise RuntimeError(_tr('系统不支持修改此账户设置。'))
        if current[field] != expected[field]:
            raise RuntimeError(_tr('账户信息已被其他程序修改，请刷新后重试。'))
    applied = []
    try:
        for field, value in changes.items():
            if value != current[field]:
                set_account_field(field, value)
                applied.append(field)
    except Exception as original:
        failures = []
        for field in reversed(applied):
            try:
                set_account_field(field, current[field])
            except Exception as rollback:
                failures.append(str(rollback))
        if failures:
            raise RuntimeError(_tr('账户设置未完全应用，恢复也未完成：%s') % '; '.join(failures)) from original
        if applied:
            raise RuntimeError(_tr('账户设置失败，先前的设置已恢复。') + '\n' + str(original)) from original
        raise


def region_snapshot():
    account = pwd.getpwuid(os.getuid())
    language = os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG') or 'C'
    result = {'username': account.pw_name, 'name': account.pw_gecos.split(',')[0] or account.pw_name,
            'language': language,
            'time': os.environ.get('LC_ALL') or os.environ.get('LC_TIME') or os.environ.get('LANG') or 'C',
            'numeric': os.environ.get('LC_ALL') or os.environ.get('LC_NUMERIC') or os.environ.get('LANG') or 'C',
            'desktop': os.environ.get('XDG_CURRENT_DESKTOP', '') or _tr('未知')}
    try:
        result['account'] = account_snapshot()
    except Exception as exc:
        result['account'] = None
        result['account_error'] = str(exc)
    from adws_account_header import avatar_for_user
    result['avatar_png'] = avatar_for_user(os.getuid(), (result['account'] or {}).get('avatar'))
    try:
        result['locales'] = available_locales()
    except Exception:
        result['locales'] = []
    return result


READERS = {'network': network_snapshot, 'bluetooth': bluetooth_snapshot,
           'sound': audio_snapshot, 'power': power_snapshot, 'region': region_snapshot}


def build_page(key, host):
    """Build unscrolled content. The host wraps it with its standard scroll()."""
    from gi.repository import GLib, Gtk, Pango
    if key not in READERS:
        raise KeyError(key)
    if key == 'sound':
        from adws_sound_settings import SoundSettingsPage
        page = SoundSettingsPage(host)
        page.box.system_service_page = page
        return page.box

    class ServicePage:
        def __init__(self):
            self.generation = 0
            self.closed = False
            self.loading = False
            self.account = None
            self.account_inputs = {}
            self.account_apply_button = None
            self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            self.box.get_style_context().add_class('settings-service-page')
            self.box.connect('destroy', self.destroy)
            toolbar = Gtk.Box(spacing=10)
            self.status = self.text('正在读取系统状态…', 'dim-label')
            toolbar.pack_start(self.status, True, True, 0)
            self.refresh_button = self.button('刷新状态', self.refresh)
            toolbar.pack_end(self.refresh_button, False, False, 0)
            self.box.pack_start(toolbar, False, False, 0)
            self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            self.box.pack_start(self.content, False, False, 0)
            GLib.idle_add(self.refresh)

        def text(self, text, css=None, translate=True):
            widget = Gtk.Label(label=_tr(text) if translate else str(text), xalign=0)
            widget.set_line_wrap(True)
            widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            widget.set_max_width_chars(60)
            if css:
                widget.get_style_context().add_class(css)
            return widget

        def button(self, title, callback, suggested=False):
            button = Gtk.Button(label=_tr(title))
            button.set_valign(Gtk.Align.CENTER)
            if suggested:
                button.get_style_context().add_class('suggested-action')
            button.connect('clicked', lambda *_: callback())
            return button

        def section(self, title, description=None):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            box.get_style_context().add_class('settings-card')
            box.pack_start(self.text(title, 'settings-section-title'), False, False, 0)
            if description:
                box.pack_start(self.text(description, 'dim-label'), False, False, 0)
            self.content.pack_start(box, False, False, 0)
            return box

        def row(self, box, title, detail='', control=None, icon=None, leading=None):
            row = Gtk.Box(spacing=14)
            row.set_valign(Gtk.Align.CENTER)
            row.get_style_context().add_class('settings-service-row')
            if leading is not None:
                row.pack_start(leading, False, False, 0)
            elif icon:
                image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
                row.pack_start(image, False, False, 0)
            caption = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            caption.pack_start(self.text(title), False, False, 0)
            if detail:
                caption.pack_start(self.text(detail, 'dim-label'), False, False, 0)
            row.pack_start(caption, True, True, 0)
            if control:
                row.pack_end(control, False, False, 0)
            box.pack_start(row, False, False, 0)
            return row

        def destroy(self, *_):
            self.closed = True
            self.generation += 1

        def refresh(self):
            if self.closed or getattr(host, 'closed', False) or self.loading:
                return False
            if self.account and self.account_input_changes(self.account, self.account_inputs):
                if not host.confirm('放弃尚未应用的账户修改？', '刷新会重新读取系统中的账户设置。'):
                    return False
            self.loading = True
            self.generation += 1
            generation = self.generation
            self.refresh_button.set_sensitive(False)
            self.content.set_sensitive(False)
            self.status.set_text(_tr('正在读取系统状态…'))
            def worker():
                try:
                    result, error = READERS[key](), None
                except Exception as exc:
                    result, error = None, str(exc)
                GLib.idle_add(self.loaded, generation, result, error)
            # Discovery never disables navigation or blocks closing the window.
            threading.Thread(target=worker, daemon=True).start()
            return False

        def loaded(self, generation, snapshot, error):
            if self.closed or getattr(host, 'closed', False) or generation != self.generation:
                return False
            self.loading = False
            self.refresh_button.set_sensitive(True)
            self.content.set_sensitive(True)
            if error:
                self.status.set_text(_tr('无法读取系统状态：%s') % error)
                # Preserve existing rows and pending edits after a failed
                # refresh; offer repair only when no working page exists.
                if self.content.get_children():return False
                missing=self.section('没有可用的系统服务。',error)
                def repair():
                    service='sound-server' if key=='sound' else key
                    title='安装 PipeWire 音频服务？' if key=='sound' else '安装所需系统服务？'
                    detail='将安装 PipeWire、PulseAudio 兼容层与 WirePlumber，并启用当前用户的音频服务。' if key=='sound' else '将安装后台服务，不安装 GNOME 或 KDE 控制中心。'
                    if host.confirm(title,detail):
                        from adws_native_services import install_service
                        self.change(lambda:install_service(service))
                missing.pack_start(self.button('安装所需系统服务',repair),False,False,0)
                self.content.show_all()
                return False
            for child in self.content.get_children():
                child.destroy()
            if snapshot.get('missing'):
                missing = self.section('没有可用的系统服务。', snapshot['missing'])
                def install():
                    if host.confirm('安装所需系统服务？', '将安装后台服务，不安装 GNOME 或 KDE 控制中心。'):
                        from adws_native_services import install_service
                        self.change(lambda:install_service(key))
                missing.pack_start(self.button('安装所需系统服务',install),False,False,0)
            else:
                getattr(self, 'render_' + key)(snapshot)
            self.status.set_text(_tr('账户设置由系统服务保存；语言更改在重新登录后生效。' if key == 'region'
                                     else '此页面直接使用系统服务；操作后立即生效。'))
            from adws_settings_widgets import enhance_choices
            enhance_choices(self.content, translate=_tr)
            self.content.show_all()
            return False

        def change(self, operation, confirmation=None, after=None, before_refresh=None):
            if self.loading or getattr(host, 'busy', False):
                return False
            if confirmation and not host.confirm(*confirmation):
                return False
            def completed():
                if before_refresh:
                    before_refresh()
                self.refresh()
                if after:
                    after()
            host.run_worker(operation, completed)
            return True

        def service_switch(self, active, operation, confirmation=None):
            control = Gtk.Switch()
            control.set_active(active)
            control.set_state(active)
            control.set_halign(Gtk.Align.END)
            control.set_valign(Gtk.Align.CENTER)
            restoring = [False]
            def restore():
                if not self.closed and control.get_parent() is not None:
                    restoring[0] = True
                    try:
                        control.set_active(active)
                        control.set_state(active)
                    finally:
                        restoring[0] = False
                return False
            def requested(_, desired):
                if restoring[0] or desired == active:
                    return False
                # Keep displaying the confirmed state until service discovery
                # supplies a new one. Cancellation/errors must not lie to users.
                GLib.idle_add(restore)
                self.change(lambda: operation(desired), confirmation if not desired else None)
                return True
            control.connect('state-set', requested)
            return control

        def render_network(self, data):
            if any(device[1] == 'wifi' for device in data['devices']):
                section = self.section('Wi-Fi')
                confirmation = ('关闭 Wi-Fi？', '当前的无线网络连接将会断开。') if data['wifi'] else None
                self.wifi_switch = self.service_switch(data['wifi'], lambda desired: wifi_enabled(desired), confirmation)
                self.wifi_switch.set_tooltip_text(_tr('Wi-Fi'))
                self.row(section, '已开启' if data['wifi'] else '已关闭', control=self.wifi_switch)
            section = self.section('网络设备')
            states = {'connected': '已连接', 'disconnected': '未连接', 'connecting': '连接中',
                      'unavailable': '不可用', 'unmanaged': '未托管'}
            for device, kind, state, connection in data['devices']:
                if kind == 'loopback':
                    continue
                state = states.get(state, state)
                self.row(section, device, ' · '.join(filter(None, (_tr(state), connection if connection != '--' else ''))),
                         icon='network-wireless-symbolic' if kind == 'wifi' else 'network-wired-symbolic')
            if not data['devices']:
                section.pack_start(self.text('未检测到网络设备。', 'dim-label'), False, False, 0)
            from adws_native_settings_gui import network_sections
            network_sections(host,self.content)

        def render_bluetooth(self, data):
            section = self.section('蓝牙适配器')
            if not data['adapter']:
                section.pack_start(self.text('未检测到蓝牙适配器。', 'dim-label'), False, False, 0)
                return
            confirmation = ('关闭蓝牙？', '已连接的蓝牙键盘、鼠标和耳机将会断开。') if data['powered'] else None
            self.bluetooth_switch = self.service_switch(data['powered'], lambda desired: bluetooth_power(desired), confirmation)
            self.bluetooth_switch.set_tooltip_text(_tr('蓝牙'))
            self.row(section, data['adapter'], _tr('已开启' if data['powered'] else '已关闭'),
                     self.bluetooth_switch, 'bluetooth-symbolic')
            from adws_native_settings_gui import bluetooth_sections
            bluetooth_sections(host,self.content)

        def render_power(self, data):
            section = self.section('电池')
            status = {'Charging': '正在充电', 'Discharging': '正在放电', 'Full': '已充满', 'Not charging': '未充电', 'Unknown': '未知'}
            for item in data['batteries']:
                self.row(section, item['name'], f"{item['capacity']}% · {_tr(status.get(item['status'], item['status']))}", icon='battery-symbolic')
                progress = Gtk.ProgressBar(fraction=item['capacity'] / 100)
                section.pack_start(progress, False, False, 0)
            if not data['batteries']:
                section.pack_start(self.text('未检测到电池。', 'dim-label'), False, False, 0)
            section = self.section('电源模式')
            profiles = {'power-saver': ('省电', '优先延长续航并降低功耗。'),
                        'balanced': ('平衡', '在性能与功耗之间取得平衡。'),
                        'performance': ('性能', '优先提高性能，可能增加功耗和风扇噪音。')}
            for profile in data['profiles']:
                current = profile == data['active']
                button = self.button('当前模式' if current else '使用此模式',
                                     lambda profile=profile: self.change(lambda: power_profile(profile)), current)
                button.set_sensitive(not current)
                title, detail = profiles[profile]
                self.row(section, title, _tr(detail), button)
            if not data['profiles']:
                section.pack_start(self.text(data.get('profile_error') or '系统未提供可切换的电源模式。', 'dim-label'), False, False, 0)
            from adws_native_settings_gui import power_sections
            power_sections(host,self.content)

        def render_region(self, data):
            section = self.section('当前账户')
            from adws_account_header import avatar_image
            image = avatar_image(data.get('avatar_png'), css='settings-current-avatar')
            self.row(section, data['name'], data['username'], leading=image)
            account = data.get('account')
            inputs = {}
            self.account = account
            self.account_inputs = inputs
            self.account_apply_button = None
            if account and 'name' in account['supported']:
                name = Gtk.Entry()
                name.set_text(account['name'])
                name.set_placeholder_text(data['name'])
                name.set_max_length(128)
                inputs['name'] = name
                self.row(section, '显示名称', control=name)
            elif not account:
                section.pack_start(self.text('系统没有提供可直接编辑的账户服务。', 'dim-label'), False, False, 0)
            section = self.section('语言与地区', '更改系统语言通常需要重新登录才能对所有应用生效。')
            for title, item in [('界面语言', 'language'), ('地区格式（日期与数字）', 'formats')]:
                if account and item in account['supported'] and data.get('locales'):
                    chooser = Gtk.ComboBoxText()
                    active = account.get(item) or data.get('language', '')
                    values = list(data['locales'])
                    match = next((value for value in values if locale_key(value) == locale_key(active)), None)
                    if match is None and active:
                        values.insert(0, active)
                        match = active
                    for value in values:
                        chooser.append(value, locale_title(value))
                    if match:
                        chooser.set_active_id(match)
                    else:
                        chooser.set_active(0)
                    # Keep the initial choice separate: no write should occur
                    # just because libc and AccountsService spell UTF-8 differently.
                    chooser.initial_value = chooser.get_active_id()
                    inputs[item] = chooser
                    self.row(section, title, control=chooser)
                elif item == 'language':
                    self.row(section, title, data[item])
            for title, item in [('日期格式', 'time'), ('数字格式', 'numeric'), ('当前会话', 'desktop')]:
                if item in ('time', 'numeric') and 'formats' in inputs:
                    continue
                self.row(section, title, data[item])
            if inputs:
                apply_button = self.button('应用账户设置', self.apply_pending, True)
                apply_button.set_sensitive(False)
                self.account_apply_button = apply_button
                section.pack_start(apply_button, False, False, 0)
                for item, widget in inputs.items():
                    widget.connect('changed', self.update_account_pending)
            if account and not data.get('locales'):
                section.pack_start(self.text('没有读取到可用的系统语言。', 'dim-label'), False, False, 0)
            section.pack_start(self.button('输入法设置',lambda:host.show_page('input')),False,False,0)
            from adws_native_settings_gui import account_sections
            account_sections(host,self.content)
            self.update_account_pending()

        @staticmethod
        def account_input_changes(account, inputs):
            changed = {}
            for field, widget in inputs.items():
                if field == 'name':
                    value = widget.get_text()
                    if value != account[field]:
                        changed[field] = value
                else:
                    value = widget.get_active_id()
                    if value and value != widget.initial_value:
                        changed[field] = value
            return changed

        def update_account_pending(self, *_):
            if self.closed or getattr(host, 'closed', False):
                return False
            pending = bool(self.account and self.account_input_changes(self.account, self.account_inputs))
            if self.account_apply_button:
                self.account_apply_button.set_sensitive(pending)
            if pending:
                host.mark_dirty('region')
            else:
                host.dirty.discard('region')
                host.update_footer()
            return pending

        def apply_pending(self, after=None):
            if self.loading or getattr(host, 'busy', False):
                return False
            if not self.account:
                if after:
                    after()
                return False
            return self.apply_account_inputs(self.account, self.account_inputs, after=after)

        def apply_account_inputs(self, account, inputs, after=None):
            changes = self.account_input_changes(account, inputs)
            if not changes:
                self.update_account_pending()
                if after:
                    after()
                return False
            # Capture all widget values before moving work onto a thread.
            def saved():
                # Update baselines before refresh: successful saves should not
                # ask the user whether to discard the changes just saved.
                account.update(changes)
                for field, value in changes.items():
                    if field != 'name':
                        inputs[field].initial_value = value
                self.update_account_pending()
            def refresh_header():
                header = getattr(host, 'account_header', None)
                if header is not None:
                    header.refresh(force=True)
                if after:
                    after()
            return self.change(lambda: apply_account(account, changes), after=refresh_header, before_refresh=saved)

    page = ServicePage()
    page.box.system_service_page = page
    page.box.apply_pending = page.apply_pending
    return page.box

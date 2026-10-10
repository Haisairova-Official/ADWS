"""Native settings backends. No control centers, shell expansion or secret argv."""
import ipaddress
import json
import math
import os
from pathlib import Path
import pwd
import re
import shutil
import uuid

from gi.repository import Gio, GLib
from adws_i18n import tr
from adws_system_pages import command

NM = 'org.freedesktop.NetworkManager'
NM_ROOT = '/org/freedesktop/NetworkManager'
NM_SETTINGS = NM_ROOT + '/Settings'


def bus_call(destination, path, interface, method, signature=None, values=(), *, session=False, timeout=8000):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION if session else Gio.BusType.SYSTEM, None)
    args = GLib.Variant(signature, values) if signature else None
    return bus.call_sync(destination, path, interface, method, args, None,
                         Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, timeout, None)


def properties(destination, path, interface):
    return bus_call(destination, path, 'org.freedesktop.DBus.Properties', 'GetAll', '(s)', (interface,)).unpack()[0]


def variants(reply):
    """Keep nested variants intact: service updates require their original types."""
    group = reply.get_child_value(0)
    result = {}
    for i in range(group.n_children()):
        item = group.get_child_value(i)
        name, values = item.get_child_value(0).get_string(), item.get_child_value(1)
        result[name] = {values.get_child_value(j).get_child_value(0).get_string():
                        values.get_child_value(j).get_child_value(1).get_variant()
                        for j in range(values.n_children())}
    return result


def nm_profiles():
    active={}
    for path in properties(NM,NM_ROOT,NM).get('ActiveConnections',[]):
        details=properties(NM,path,NM+'.Connection.Active')
        active[details.get('Connection')]=path
    paths = bus_call(NM, NM_SETTINGS, NM + '.Settings', 'ListConnections').unpack()[0]
    result = []
    for path in paths:
        try:
            settings = variants(bus_call(NM, path, NM + '.Settings.Connection', 'GetSettings'))
            general = {key: value.unpack() for key, value in settings['connection'].items()}
            result.append({'path': path, 'name': general.get('id', ''), 'uuid': general.get('uuid', ''),
                           'type': general.get('type', ''), 'settings': settings, 'active': active.get(path)})
        except GLib.Error:
            continue
    return sorted(result, key=lambda item: item['name'].casefold())


def nm_wifi(scan=False):
    devices = bus_call(NM, NM_ROOT, NM, 'GetDevices').unpack()[0]
    result = []
    for device in devices:
        general = properties(NM, device, NM + '.Device')
        if general.get('DeviceType') != 2:
            continue
        if scan:
            bus_call(NM, device, NM + '.Device.Wireless', 'RequestScan', '(a{sv})', ({},))
        wireless = properties(NM, device, NM + '.Device.Wireless')
        for path in bus_call(NM, device, NM + '.Device.Wireless', 'GetAccessPoints').unpack()[0]:
            ap = properties(NM, path, NM + '.AccessPoint')
            raw_ssid = bytes(ap.get('Ssid', []))
            if not raw_ssid:
                continue
            security = ap.get('RsnFlags', 0) | ap.get('WpaFlags', 0)
            result.append({'ssid': raw_ssid, 'name': raw_ssid.decode('utf-8', 'replace'),
                           'device': device, 'path': path, 'signal': ap.get('Strength', 0),
                           'security': 'enterprise' if security & 0x200 else 'sae' if security & 0x400 else
                                       'wpa-psk' if security else 'wep' if ap.get('Flags', 0) & 1 else 'open',
                           'active': wireless.get('ActiveAccessPoint') == path})
    # Several radios/APs for one SSID must not make the menu unusable. Keep the
    # strongest candidate, but distinguish different security capabilities.
    unique = {}
    for item in sorted(result, key=lambda item: item['signal'], reverse=True):
        unique.setdefault((item['ssid'], item['security']), item)
    return list(unique.values())


def text(value, maximum=256, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum or any(ord(c) < 32 or ord(c)==127 for c in value):
        raise ValueError(tr('请输入有效内容。'))
    return value


def ip_settings(version, method, addresses='', gateway='', dns=''):
    if method not in ('auto', 'manual', 'disabled', 'link-local'):
        raise ValueError('Invalid IP method')
    result = {'method': GLib.Variant('s', method)}
    records = []
    for value in re.split(r'[,\s]+', addresses.strip()):
        if not value:
            continue
        interface = ipaddress.ip_interface(value)
        if interface.version != version:
            raise ValueError(tr('IP 地址与协议版本不匹配。'))
        records.append({'address': GLib.Variant('s', str(interface.ip)), 'prefix': GLib.Variant('u', interface.network.prefixlen)})
    if method == 'manual' and not records:
        raise ValueError(tr('手动地址模式需要至少一个 IP 地址与前缀。'))
    if records:
        result['address-data'] = GLib.Variant('aa{sv}', records)
    if gateway.strip():
        address = ipaddress.ip_address(gateway.strip())
        if address.version != version:
            raise ValueError(tr('网关与协议版本不匹配。'))
        result['gateway'] = GLib.Variant('s', str(address))
    servers = []
    for value in re.split(r'[,\s]+', dns.strip()):
        if value:
            address = ipaddress.ip_address(value)
            if address.version != version:
                raise ValueError(tr('DNS 地址与协议版本不匹配。'))
            servers.append(str(address))
    result['dns-data'] = GLib.Variant('as', servers)
    result['ignore-auto-dns'] = GLib.Variant('b', bool(servers))
    return result


def wifi_settings(name, ssid, security, password='', identity='', ca='', eap='peap', client='', private_key='', key_password=''):
    name = text(name)
    ssid = ssid.encode('utf-8') if isinstance(ssid, str) else bytes(ssid)
    if not 1 <= len(ssid) <= 32:
        raise ValueError(tr('Wi-Fi 名称必须为 1–32 字节。'))
    settings = {'connection': {'id': GLib.Variant('s', name), 'uuid': GLib.Variant('s', str(uuid.uuid4())),
                'type': GLib.Variant('s', '802-11-wireless'), 'autoconnect': GLib.Variant('b', True),
                'permissions': GLib.Variant('as', ['user:' + pwd.getpwuid(os.getuid()).pw_name + ':'])},
                '802-11-wireless': {'ssid': GLib.Variant('ay', ssid), 'mode': GLib.Variant('s', 'infrastructure')},
                'ipv4': ip_settings(4, 'auto'), 'ipv6': ip_settings(6, 'auto')}
    if security == 'open':
        return settings
    if security not in ('wpa-psk','sae','enterprise','wep'):
        raise ValueError('Invalid Wi-Fi security')
    settings['802-11-wireless-security'] = {'key-mgmt': GLib.Variant('s', 'wpa-eap' if security == 'enterprise' else 'none' if security=='wep' else security)}
    if security == 'enterprise':
        if eap not in ('peap', 'ttls', 'tls'):
            raise ValueError('Invalid EAP method')
        text(identity)
        if eap!='tls':text(password,256)
        certificate = Path(ca).expanduser()
        if not certificate.is_file():
            raise ValueError(tr('企业网络需要有效的 CA 证书以验证服务器。'))
        settings['802-1x'] = {'eap': GLib.Variant('as', [eap]), 'identity': GLib.Variant('s', identity),
                            'ca-cert': GLib.Variant('ay', (certificate.resolve().as_uri()+'\0').encode()),
                            }
        if eap=='tls':
            for key,filename in [('client-cert',client),('private-key',private_key)]:
                location=Path(filename).expanduser()
                if not filename or not location.is_file():raise ValueError(tr('TLS 认证需要客户端证书和私钥文件。'))
                settings['802-1x'][key]=GLib.Variant('ay',(location.resolve().as_uri()+'\0').encode())
            if key_password:settings['802-1x']['private-key-password']=GLib.Variant('s',text(key_password,1024))
        else:
            settings['802-1x'].update({'password':GLib.Variant('s',password),'phase2-auth':GLib.Variant('s','mschapv2')})
    elif security=='wep':
        if not (len(password) in (5,13) and password.isascii() or len(password) in (10,26) and re.fullmatch('[0-9a-fA-F]+',password)):
            raise ValueError(tr('WEP 密钥须为 5/13 个 ASCII 字符或 10/26 位十六进制。'))
        settings['802-11-wireless-security'].update({'wep-key0':GLib.Variant('s',password),'wep-key-type':GLib.Variant('u',1),'wep-tx-keyidx':GLib.Variant('u',0)})
    else:
        text(password, 64)
        if security == 'wpa-psk' and not (8 <= len(password) <= 63 or re.fullmatch('[0-9a-fA-F]{64}', password)):
            raise ValueError(tr('WPA 密码须为 8–63 个字符或 64 位十六进制密钥。'))
        settings['802-11-wireless-security']['psk'] = GLib.Variant('s', password)
    return settings


def nm_create(settings, device='/', access_point='/', activate=True):
    path = bus_call(NM, NM_SETTINGS, NM + '.Settings', 'AddConnection2', '(a{sa{sv}}ua{sv})', (settings, 1, {}), timeout=60000).unpack()[0]
    if activate:
        # A failed activation keeps the valid profile for correction/retry.
        bus_call(NM, NM_ROOT, NM, 'ActivateConnection', '(ooo)', (path, device, access_point), timeout=60000)
    return path


def nm_update(profile, updates):
    path = profile['path']
    current = variants(bus_call(NM, path, NM + '.Settings.Connection', 'GetSettings'))
    if current != profile['settings']:
        raise RuntimeError(tr('网络配置已被其他程序修改，请刷新后重试。'))
    candidate = {group:dict(values) for group,values in current.items()}
    for group, values in updates.items():
        candidate.setdefault(group, {}).update(values)
        if group in ('ipv4','ipv6'):
            # Never send conflicting legacy/new representations.
            if 'address-data' in values:candidate[group].pop('addresses',None)
            if 'dns-data' in values:candidate[group].pop('dns',None)
    # Preserve credentials withheld by GetSettings, including VPN/WireGuard.
    for group in ('802-11-wireless-security', '802-1x', 'vpn', 'wireguard'):
        if group in current:
            secrets = variants(bus_call(NM, path, NM + '.Settings.Connection', 'GetSecrets', '(s)', (group,), timeout=60000))
            for setting, values in secrets.items():
                for name, value in values.items():
                    existing=candidate.setdefault(setting,{})
                    if setting=='vpn' and name=='secrets' and name in existing:
                        merged=value.unpack();merged.update(existing[name].unpack());existing[name]=GLib.Variant('a{ss}',merged)
                    elif setting=='wireguard' and name=='peers' and name in existing:
                        # GetSettings can omit per-peer preshared keys. Retain
                        # those keys while preserving the public peer config.
                        peers=existing[name].unpack();secret_peers={p.get('public-key'):p for p in value.unpack()}
                        for peer in peers:
                            for key,secret in secret_peers.get(peer.get('public-key'),{}).items():peer.setdefault(key,secret)
                        existing[name]=GLib.Variant('aa{sv}',[{k:GLib.Variant('s',v) if isinstance(v,str) else GLib.Variant('u',v) if type(v) is int else GLib.Variant('as',v) for k,v in peer.items()} for peer in peers])
                    else:existing.setdefault(name,value)
    bus_call(NM, path, NM + '.Settings.Connection', 'Update2', '(a{sa{sv}}ua{sv})', (candidate, 1, {}), timeout=60000)


def nm_activate(profile,enabled):
    path=profile['path']
    if not re.fullmatch(re.escape(NM_SETTINGS)+r'/\d+',path) or type(enabled) is not bool:raise ValueError('Invalid connection')
    if enabled:
        bus_call(NM,NM_ROOT,NM,'ActivateConnection','(ooo)',(path,'/','/'),timeout=60000)
    else:
        active=profile.get('active')
        if not active or not re.fullmatch(re.escape(NM_ROOT)+r'/ActiveConnection/\d+',active):raise ValueError('Invalid active connection')
        bus_call(NM,NM_ROOT,NM,'DeactivateConnection','(o)',(active,),timeout=60000)


def nm_delete(path):
    if not re.fullmatch(re.escape(NM_SETTINGS) + r'/\d+', path):
        raise ValueError('Invalid connection path')
    bus_call(NM, path, NM + '.Settings.Connection', 'Delete', timeout=60000)


def vpn_import(provider, filename):
    if provider not in ('openvpn', 'wireguard', 'vpnc', 'openconnect'):
        raise ValueError('Invalid VPN provider')
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(tr('VPN 配置文件无效或过大。'))
    command(['nmcli', '--wait', '20', 'connection', 'import', 'type', provider, 'file', str(path)], timeout=25)


def audio_advanced():
    from concurrent.futures import ThreadPoolExecutor
    names = ('sink-inputs', 'source-outputs', 'cards', 'sinks', 'sources')
    with ThreadPoolExecutor(max_workers=3) as pool:
        raw = list(pool.map(lambda name: command(['pactl', '-f', 'json', 'list', name]), names))
    return dict(zip(names, (json.loads(value) for value in raw)))


def audio_set(kind, index, action, value):
    allowed = {'sink-input': ('volume', 'mute', 'move'), 'source-output': ('volume', 'mute', 'move'),
               'sink': ('port', 'channels'), 'source': ('port', 'channels'), 'card': ('profile',)}
    if kind not in allowed or action not in allowed[kind] or type(index) is not int or index < 0:
        raise ValueError('Invalid audio operation')
    if action == 'volume':
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError('Invalid audio volume')
        args = ['set-' + kind + '-volume', str(index), f'{round(value)}%']
    elif action == 'mute':
        if type(value) is not bool:
            raise ValueError('Invalid mute state')
        args = ['set-' + kind + '-mute', str(index), '1' if value else '0']
    elif action == 'move':
        if type(value) is not int or value < 0:
            raise ValueError('Invalid audio target')
        args = ['move-' + kind, str(index), str(value)]
    elif action == 'channels':
        if not isinstance(value, list) or not value or len(value)>32 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100 for v in value):
            raise ValueError('Invalid channel volumes')
        args = ['set-' + kind + '-volume', str(index), *(f'{round(v)}%' for v in value)]
    else:
        if not isinstance(value, str) or value.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.:@+-]+', value):
            raise ValueError('Invalid audio profile/port')
        args = ['set-' + kind + '-' + action, str(index), value]
    command(['pactl', *args])


PACKAGES = {
    'network': {'pacman':['networkmanager'], 'apt-get':['network-manager'], 'dnf':['NetworkManager']},
    'bluetooth': {'pacman':['bluez','bluez-utils'], 'apt-get':['bluez'], 'dnf':['bluez']},
    'sound': {'pacman':['libpulse'], 'apt-get':['pulseaudio-utils'], 'dnf':['pulseaudio-utils']},
    'sound-server': {'pacman':['pipewire','pipewire-pulse','wireplumber'], 'apt-get':['pipewire','pipewire-pulse','wireplumber','pulseaudio-utils'], 'dnf':['pipewire','pipewire-pulseaudio','wireplumber','pulseaudio-utils']},
    'region': {'pacman':['accountsservice'], 'apt-get':['accountsservice'], 'dnf':['accountsservice']},
    'power': {'pacman':['power-profiles-daemon','swayidle'], 'apt-get':['power-profiles-daemon','swayidle'], 'dnf':['power-profiles-daemon','swayidle']},
    'vpn-openvpn':{'pacman':['networkmanager-openvpn'],'apt-get':['network-manager-openvpn'],'dnf':['NetworkManager-openvpn']},
    'vpn-openconnect':{'pacman':['networkmanager-openconnect'],'apt-get':['network-manager-openconnect'],'dnf':['NetworkManager-openconnect']},
    'vpn-vpnc':{'pacman':['networkmanager-vpnc'],'apt-get':['network-manager-vpnc'],'dnf':['NetworkManager-vpnc']},
    'ibus':{'pacman':['ibus'],'apt-get':['ibus','gir1.2-ibus-1.0'],'dnf':['ibus']},
    'input': {'pacman':['fcitx5','fcitx5-chinese-addons'], 'apt-get':['fcitx5','fcitx5-chinese-addons','libime-bin'], 'dnf':['fcitx5','fcitx5-chinese-addons']},
}


def install_service(key):
    manager = next((name for name in ('pacman','apt-get','dnf') if shutil.which(name)), None)
    if key not in PACKAGES or not manager or not shutil.which('pkexec'):
        raise RuntimeError(tr('无法自动安装，请使用系统软件管理器补齐所需服务。'))
    args = ['pkexec', shutil.which(manager), *(['-S','--needed','--noconfirm'] if manager=='pacman' else ['install','-y']), *PACKAGES[key][manager]]
    command(args, timeout=600)
    if key=='sound-server':
        command(['systemctl','--user','enable','--now','pipewire.socket','pipewire-pulse.socket','wireplumber.service'],timeout=45)
    unit = {'network':'NetworkManager','bluetooth':'bluetooth','region':'accounts-daemon','power':'power-profiles-daemon'}.get(key)
    if unit:
        command(['pkexec', shutil.which('systemctl') or '/usr/bin/systemctl', 'enable', '--now', unit], timeout=45)


FCITX = 'org.fcitx.Fcitx5'
FCITX_INTERFACE = 'org.fcitx.Fcitx.Controller1'


def fcitx_call(method, signature=None, values=()):
    return bus_call(FCITX, '/controller', FCITX_INTERFACE, method, signature, values, session=True)


def fcitx_snapshot():
    current = fcitx_call('CurrentInputMethodGroup').unpack()[0]
    layout, enabled = fcitx_call('InputMethodGroupInfo', '(s)', (current,)).unpack()
    return {'group': current, 'layout': layout, 'enabled': enabled,
            'available': fcitx_call('AvailableInputMethods').unpack()[0],
            'addons': fcitx_call('GetAddons').unpack()[0]}


def fcitx_set_group(expected, entries):
    current = fcitx_snapshot()
    if current['group'] != expected['group'] or current['enabled'] != expected['enabled']:
        raise RuntimeError(tr('输入法列表已被修改，请刷新后重试。'))
    known = {item[0] for item in current['available']}
    if not entries or len({item[0] for item in entries}) != len(entries) or any(item[0] not in known for item in entries):
        raise ValueError(tr('输入法列表无效；请至少保留一种输入法。'))
    fcitx_call('SetInputMethodGroupInfo', '(ssa(ss))', (current['group'], current['layout'], entries))
    fcitx_call('Save')


def fcitx_config(uri):
    if not (uri == 'fcitx://config/global' or re.fullmatch(r'fcitx://config/(?:addon|inputmethod)/[A-Za-z0-9_.+/-]+', uri)):
        raise ValueError('Invalid input-method config URI')
    return fcitx_call('GetConfig', '(s)', (uri,))


def fcitx_set_config(uri, expected, value):
    if fcitx_config(uri).get_child_value(0) != expected:
        raise RuntimeError(tr('输入法设置已被其他程序修改，请刷新后重试。'))
    fcitx_call('SetConfig', '(sv)', (uri, value))
    fcitx_call('Save')

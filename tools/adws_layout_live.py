"""Read-only, bounded snapshots for the layout editor; never launches components."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def _json(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=1.5)
        return json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def read_snapshot():
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib
    result = {'windows': [], 'workspaces': [], 'tray': [], 'icons': {}, 'pins': []}
    if shutil.which('niri') and os.environ.get('NIRI_SOCKET'):
        result['windows'] = _json(['niri', 'msg', '-j', 'windows'])
        result['workspaces'] = _json(['niri', 'msg', '-j', 'workspaces'])
    elif shutil.which('hyprctl') and os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        result['windows'] = [{'id': w.get('address'), 'app_id': w.get('class'), 'title': w.get('title'),
                              'workspace_id': w.get('workspace', {}).get('id'), 'is_focused': False,
                              'layout': {'pos_in_scrolling_layout': [w.get('at', [0, 0])[0], w.get('at', [0, 0])[1]]}}
                             for w in _json(['hyprctl', '-j', 'clients'])]
        result['workspaces'] = [{'id': w.get('id'), 'idx': w.get('id'), 'is_active': True,
                                  'output': w.get('monitor')} for w in _json(['hyprctl', '-j', 'workspaces'])]
    for app in Gio.AppInfo.get_all():
        icon = app.get_icon()
        if icon:
            result['icons'][app.get_id().removesuffix('.desktop').lower()] = icon.to_string()
    path = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/taskbar-pins.json'
    try: result['pins'] = json.loads(path.read_text()).get('apps', [])
    except (OSError, ValueError): pass
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        items = bus.call_sync('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher',
            'org.freedesktop.DBus.Properties', 'Get', GLib.Variant('(ss)',
            ('org.kde.StatusNotifierWatcher', 'RegisteredStatusNotifierItems')), None,
            Gio.DBusCallFlags.NO_AUTO_START, 400, None).unpack()[0]
        for address in list(items)[:64]:
            service, _, path = address.partition('/')
            try:
                props = bus.call_sync(service, '/'+path if path else '/StatusNotifierItem',
                    'org.freedesktop.DBus.Properties', 'GetAll', GLib.Variant('(s)',
                    ('org.kde.StatusNotifierItem',)), None, Gio.DBusCallFlags.NO_AUTO_START, 200, None).unpack()[0]
                if props.get('Status') == 'Passive': continue
                attention = props.get('Status') == 'NeedsAttention'
                names = [props.get('AttentionIconName')] if attention else []
                names.append(props.get('IconName'))
                pixmaps = props.get('AttentionIconPixmap', []) if attention else []
                if not pixmaps: pixmaps = props.get('IconPixmap', [])
                pixmaps = [(w, h, bytes(data)) for w, h, data in pixmaps
                           if 0 < w <= 512 and 0 < h <= 512 and len(data) == w*h*4]
                pixmap = min(pixmaps, key=lambda p: abs(p[0]-32)+abs(p[1]-32)) if pixmaps else None
                result['tray'].append({'name': props.get('Title', ''), 'icons': [n for n in names if n],
                                       'theme_path': props.get('IconThemePath', ''), 'pixmap': pixmap})
            except GLib.Error: continue
    except GLib.Error: pass
    try:
        from adws_quick_controls import status
        result['sound'] = status('sound')
    except Exception: pass
    # DDC discovery is expensive. Preview brightness uses its actual symbol;
    # values and unavailable status are obtained from the control's shared cache.
    result['brightness'] = {'icon': 'display-brightness-symbolic'}
    from adws_plugin_preview import read
    result['plugins'] = read()
    return result


def window_cards(live, options):
    """Match active-workspace filtering, pins, grouping and tiling order."""
    workspaces = {w['id']: w for w in live.get('workspaces', [])}
    active = {w['id'] for w in workspaces.values() if w.get('is_active')}
    windows = [w for w in live.get('windows', [])
               if not active or w.get('workspace_id') in active]
    windows.sort(key=lambda w: (workspaces.get(w.get('workspace_id'), {}).get('idx', 0),
                               tuple(w.get('layout', {}).get('pos_in_scrolling_layout') or (0, 0))))
    grouped, cards = {}, []
    for window in windows:
        key = (window.get('app_id') or '').removesuffix('.desktop').lower()
        if options.get('group_windows', True) and key and key in grouped:
            card = grouped[key]; card['count'] += 1
            card['focused'] |= window.get('is_focused', False)
            continue
        card = {'app_id': key, 'icon': live.get('icons', {}).get(key, key or 'application-x-executable'),
                'title': window.get('title', ''), 'focused': window.get('is_focused', False), 'count': 1}
        grouped[key] = card; cards.append(card)
    pins = []
    for pin in live.get('pins', []):
        key = str(pin.get('app_id', '')).removesuffix('.desktop').lower()
        if key not in grouped:
            desktop = str(pin.get('desktop_id', key)).removesuffix('.desktop').lower()
            pins.append({'app_id': key, 'icon': live.get('icons', {}).get(desktop, key),
                         'focused': False, 'count': 0, 'title': pin.get('name', '')})
    return pins + cards

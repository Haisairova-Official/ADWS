"""Session-specific display discovery and reversible runtime configuration."""
import json
import math
import os
import re
import subprocess

TRANSFORMS = ('normal', '90', '180', '270', 'flipped', 'flipped-90', 'flipped-180', 'flipped-270')


def detect_session(env=None):
    env = os.environ if env is None else env
    if env.get('XDG_SESSION_TYPE', '').casefold() == 'x11':
        return None  # Ignore inherited sockets from an earlier Wayland session.
    desktop = env.get('XDG_CURRENT_DESKTOP', '').casefold().split(':')
    # An inherited socket from another compositor must not override the active desktop.
    if 'hyprland' in desktop and env.get('HYPRLAND_INSTANCE_SIGNATURE'):
        return 'hyprland'
    if 'niri' in desktop and env.get('NIRI_SOCKET'):
        return 'niri'
    if env.get('NIRI_SOCKET') and not env.get('HYPRLAND_INSTANCE_SIGNATURE'):
        return 'niri'
    if env.get('HYPRLAND_INSTANCE_SIGNATURE') and not env.get('NIRI_SOCKET'):
        return 'hyprland'
    return None


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=8, check=True)
    return result.stdout


def mode_string(width, height, refresh):
    return f'{int(width)}x{int(height)}@{float(refresh):.3f}'


def outputs(session):
    if session == 'niri':
        raw = json.loads(run(['niri', 'msg', '--json', 'outputs']))
        result = []
        for name, output in raw.items():
            modes = [mode_string(m['width'], m['height'], m['refresh_rate'] / 1000) for m in output['modes']]
            index = output.get('current_mode')
            logical = output.get('logical') or {}
            if index is None or not logical:
                continue  # Never offer an unsafe enable/disable action on this screen.
            result.append(dict(name=name, description=' '.join((output.get('make', ''), output.get('model', ''))).strip(), modes=modes, mode=modes[index], scale=logical['scale'], x=logical['x'], y=logical['y'], transform=TRANSFORMS.index(logical['transform'].casefold().replace('flipped90', 'flipped-90').replace('flipped180', 'flipped-180').replace('flipped270', 'flipped-270').lstrip('_').replace('_', '-'))))
        for monitor in result:
            geometry = raw[monitor['name']]['logical']
            monitor['logical_geometry'] = [monitor['mode'], monitor['scale'], monitor['transform'], geometry.get('width'), geometry.get('height')]
        return result
    if session == 'hyprland':
        raw = json.loads(run(['hyprctl', '-j', 'monitors']))
        result = []
        for output in raw:
            current = mode_string(output['width'], output['height'], output['refreshRate'])
            modes = [re.sub(r'Hz$', '', m) for m in output.get('availableModes', [])]
            if current not in modes:
                modes.insert(0, current)
            result.append(dict(name=output['name'], description=output.get('description', ''), modes=modes, mode=current, scale=output['scale'], x=output['x'], y=output['y'], transform=output.get('transform', 0)))
        return result
    raise ValueError('No supported compositor session')


def validate(value):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', value['name']):
        raise ValueError('Invalid display name')
    if not re.fullmatch(r'\d+x\d+@\d+(?:\.\d+)?', value['mode']):
        raise ValueError('Invalid display mode')
    parse_mode(value['mode'])
    scale = float(value['scale'])
    if not math.isfinite(scale) or not 0.5 <= scale <= 4:
        raise ValueError('Invalid display scale')
    if value['transform'] not in range(8):
        raise ValueError('Invalid display rotation')
    if any(type(value[k]) is not int or abs(value[k]) > 32768 for k in ('x', 'y')):
        raise ValueError('Invalid display position')
    return value


def apply(session, value):
    validate(value)
    name = value['name']
    if session == 'niri':
        actions = [('mode', value['mode']), ('scale', str(value['scale'])), ('transform', TRANSFORMS[value['transform']]), ('position', 'set', '--', str(value['x']), str(value['y']))]
        for action in actions:
            run(['niri', 'msg', 'output', name, *action])
    elif session == 'hyprland':
        spec = f"{name},{value['mode']},{value['x']}x{value['y']},{value['scale']},transform,{value['transform']}"
        response = run(['hyprctl', 'keyword', 'monitor', spec])
        if response.strip().casefold() != 'ok':
            raise RuntimeError(response.strip())
    else:
        raise ValueError('No supported compositor session')


def preview(session, old, new):
    """Restore every changed field if a partially applied request fails."""
    if old['name'] != new['name'] or new['mode'] not in old['modes']:
        raise ValueError('Mode is not available on this display')
    try:
        apply(session, new)
    except Exception as error:
        try:
            apply(session, old)
        except Exception as rollback_error:
            raise RuntimeError(f'{error}; restore failed: {rollback_error}') from error
        raise


def parse_mode(mode):
    match = re.fullmatch(r'(\d+)x(\d+)@(\d+(?:\.\d+)?)', str(mode))
    if not match:
        raise ValueError('Invalid display mode')
    width, height, refresh = int(match[1]), int(match[2]), float(match[3])
    if not 0 < width <= 32768 or not 0 < height <= 32768 or not 0 < refresh <= 2000:
        raise ValueError('Invalid display mode')
    return width, height, refresh


def logical_size(output):
    """Size of a monitor in compositor coordinates, including scale/rotation."""
    known = output.get('logical_geometry')
    if known and known[:3] == [output['mode'], output['scale'], output['transform']] and all(isinstance(n, int) and n > 0 for n in known[3:]):
        return tuple(known[3:])
    width, height, _ = parse_mode(output['mode'])
    if int(output['transform']) % 2:
        width, height = height, width
    scale = float(output['scale'])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid display scale')
    return max(1, math.floor(width / scale)), max(1, math.floor(height / scale))


def layout_bounds(monitors):
    if not monitors:
        return (0, 0, 1, 1)
    rectangles = [(m['x'], m['y'], *logical_size(m)) for m in monitors]
    left = min(r[0] for r in rectangles)
    top = min(r[1] for r in rectangles)
    return (left, top, max(r[0] + r[2] for r in rectangles) - left,
            max(r[1] + r[3] for r in rectangles) - top)


def snapped_position(monitor, others, x, y, threshold=24):
    """Snap neighbouring edges and centres without changing other monitors."""
    width, height = logical_size(monitor)
    snap_x, snap_y = [], []
    for other in others:
        if other['name'] == monitor['name']:
            continue
        ow, oh = logical_size(other)
        ox, oy = other['x'], other['y']
        # Only adjoining edges attract. Origin/end alignment is useful on
        # the perpendicular axis, but must not snap a monitor inside another.
        beside = min(abs(x + width - ox), abs(x - ox - ow)) <= threshold
        above = min(abs(y + height - oy), abs(y - oy - oh)) <= threshold
        if y <= oy + oh + threshold and y + height >= oy - threshold:
            snap_x.extend((ox - width, ox + ow))
        if x <= ox + ow + threshold and x + width >= ox - threshold:
            snap_y.extend((oy - height, oy + oh))
        if beside:
            snap_y.extend((oy, oy + oh - height, oy + (oh-height)/2))
        if above:
            snap_x.extend((ox, ox + ow - width, ox + (ow-width)/2))
    def nearest(value, candidates):
        if candidates:
            result = min(candidates, key=lambda p: abs(p - value))
            if abs(result - value) <= threshold:
                value = result
        return max(-32768, min(32768, int(round(value))))
    return nearest(x, snap_x), nearest(y, snap_y)


def same_settings(left, right):
    return (left['name'] == right['name'] and parse_mode(left['mode']) == parse_mode(right['mode'])
            and abs(float(left['scale']) - float(right['scale'])) < .0001
            and all(left[key] == right[key] for key in ('x', 'y', 'transform')))


def restore_all(session, monitors):
    """Attempt every monitor even when one disconnected during restoration."""
    failures = []
    for monitor in reversed(monitors):
        try:
            apply(session, monitor)
        except Exception as error:
            failures.append(f"{monitor['name']}: {error}")
    if failures:
        raise RuntimeError('; '.join(failures))


def preview_all(session, old, new):
    """Validate the whole layout first and roll back all touched outputs on error.

    Compositor commands are sequential, so atomicity here is transactional:
    a failed monitor update restores every preceding update and the partial one.
    """
    original = {item['name']: item for item in old}
    if (len(original) != len(old) or len({item['name'] for item in new}) != len(new)
            or set(original) != {item['name'] for item in new}):
        raise ValueError('Connected displays changed; refresh the display list')
    for item in new:
        validate(item)
        requested = parse_mode(item['mode'])
        if requested not in [parse_mode(mode) for mode in original[item['name']]['modes']]:
            raise ValueError('Mode is not available on this display')
    touched = []
    try:
        for item in new:
            previous = original[item['name']]
            if same_settings(previous, item):
                continue
            touched.append(previous)
            apply(session, item)
    except Exception as error:
        try:
            restore_all(session, touched)
        except Exception as restore_error:
            raise RuntimeError(f'{error}; restore failed: {restore_error}') from error
        raise
    return touched

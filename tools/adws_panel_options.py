"""Validated ADWS 1.30 panel options shared by CLI rendering and settings."""
import re
from adws_i18n import tr as _tr

DEFAULTS = {
    'position': 'bottom', 'thickness': 36, 'window_rows': 1,
    'group_windows': True, 'window_peek': False, 'window_animations': False, 'tab_animations': False,
    'animation_duration': 280, 'hover_color': '', 'focus_color': '',
    'focus_text_color': '', 'urgent_color': '',
}


def validate(options):
    result = {key: options.get(key, value) for key, value in DEFAULTS.items()}
    if result['position'] not in ('top', 'bottom', 'left', 'right'):
        raise ValueError(_tr('任务栏位置无效。'))
    for key, low, high in [('thickness', 24, 160), ('window_rows', 1, 2), ('animation_duration', 80, 1000)]:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or not low <= value <= high:
            raise ValueError(_tr('任务栏设置超出范围：%s') % key)
        result[key] = int(value)
    for key in ('group_windows', 'window_peek', 'window_animations', 'tab_animations'):
        if not isinstance(result[key], bool):
            raise ValueError(_tr('任务栏开关值无效：%s') % key)
    for key in ('hover_color', 'focus_color', 'focus_text_color', 'urgent_color'):
        value = result[key]
        if not isinstance(value, str):
            raise ValueError(_tr('任务栏颜色无效：%s') % key)
        if value and not (re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]|[0-9a-fA-F]{3}|[0-9a-fA-F]{5})?', value)
                          or re.fullmatch(r'rgba?\([\d., %]+\)', value)):
            raise ValueError(_tr('任务栏颜色无效：%s') % key)
    if result["window_rows"] == 2:
        result["thickness"] = max(48, result["thickness"])
    return result


def geometry(config, options):
    """Thickness is the short axis; the compositor determines the long axis."""
    inherited = dict(options)
    inherited.setdefault('position', config.get('position', 'bottom'))
    inherited.setdefault('thickness', config.get('width' if inherited['position'] in ('left','right') else 'height', 36))
    values = validate(inherited)
    vertical = values['position'] in ('left', 'right')
    # Older installations keep their existing geometry until explicitly changed.
    if any(key in options for key in ('position','thickness','window_rows')):
        config['position'] = values['position']
        config.pop('width' if not vertical else 'height', None)
        config['width' if vertical else 'height'] = values['thickness']
        # Only the outer edge and bar ends need screen padding. An inward
        # margin also enlarges the compositor's reserved area above the tiles.
        inward = {'bottom': 'top', 'top': 'bottom', 'left': 'right', 'right': 'left'}[values['position']]
        for side in ('top', 'bottom', 'left', 'right'):
            config['margin-' + side] = 0 if side == inward else 8
    return values, vertical


def styles(options):
    values = validate(options)
    lines = []
    for key, selector, prop in [
        ('focus_color', '.niri-taskbar button.focused', 'background-color'),
        ('focus_text_color', '.niri-taskbar button.focused', 'color'),
        ('urgent_color', '.niri-taskbar button.urgent', 'background-color'),
        ('hover_color', '.niri-taskbar button:hover:not(.focused)', 'background-color'),
    ]:
        if values[key]:
            lines.append(f'{selector} {{ background-image: none; {prop}: {values[key]}; }}')
    transition = (f'background-color {values["animation_duration"]}ms cubic-bezier(0.4, 0, 0.2, 1), '
                  f'color {values["animation_duration"]}ms ease-in-out') if values['window_animations'] else 'none'
    lines.append(f'.niri-taskbar button {{ min-width: 0; min-height: 0; transition: {transition}; }}')
    start_transition = f'background-color {values["animation_duration"]}ms ease-in-out, color {values["animation_duration"]}ms ease-in-out' if values['window_animations'] else 'none'
    lines.append(f'#custom-applauncher {{ transition: {start_transition}; }}')
    if values['position'] in ('left', 'right'):
        lines.append('#clock, #custom-applauncher { min-width: 0; padding: 0.3em 0; }')
        lines.append('.niri-taskbar { padding: 0.35em 0; } .niri-taskbar button { padding: 0.55em 0.12em; }')
        lines.append(f'#clock {{ font-size: {min(16.6, values["thickness"] / 5):.2f}px; }}')
    from adws_clock import preferences, display_pattern
    clock = preferences(options)
    if '\n' in display_pattern(clock):
        size = min(16.6, values['thickness'] / (5 if values['position'] in ('left', 'right') else 3.2))
        lines.append(f'window#waybar #clock {{ font-size: {size:.2f}px; padding-top: 0; padding-bottom: 0; }}')
    return '\n'.join(lines)

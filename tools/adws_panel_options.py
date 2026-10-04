"""Validated ADWS 1.30 panel options shared by CLI rendering and settings."""
import re
from adws_i18n import tr as _tr

DEFAULTS = {
    'split_center_corners': 'same', 'termination_mode': 'shift', 'split_panel': False, 'panel_mode': 'floating', 'panel_material': 'solid', 'surface_color': '',
    'position': 'bottom', 'thickness': 36, 'window_rows': 1,
    'group_windows': True, 'window_peek': False, 'window_animations': False, 'tab_animations': False,
    'animation_duration': 280, 'hover_color': '', 'focus_color': '',
    'focus_text_color': '', 'urgent_color': '',
}


def validate(options):
    result = {key: options.get(key, value) for key, value in DEFAULTS.items()}
    if result['split_center_corners'] == 'square':
        result['split_center_corners'] = 'pointed'
    if result['position'] not in ('top', 'bottom', 'left', 'right'):
        raise ValueError(_tr('任务栏位置无效。'))
    for key, allowed in [('split_center_corners', ('same','pointed')), ('panel_mode', ('docked','auto','floating')), ('panel_material', ('solid','mica','acrylic','candy')), ('termination_mode', ('shift','below','disabled'))]:
        if result[key] not in allowed:
            raise ValueError(_tr('任务栏设置无效：%s') % key)
    for key, low, high in [('thickness', 24, 160), ('window_rows', 1, 2), ('animation_duration', 80, 1000)]:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or not low <= value <= high:
            raise ValueError(_tr('任务栏设置超出范围：%s') % key)
        result[key] = int(value)
    for key in ('group_windows', 'window_peek', 'window_animations', 'tab_animations', 'split_panel'):
        if not isinstance(result[key], bool):
            raise ValueError(_tr('任务栏开关值无效：%s') % key)
    for key in ('hover_color', 'focus_color', 'focus_text_color', 'urgent_color', 'surface_color'):
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
    if any(key in options for key in ('position','thickness','window_rows','panel_mode')):
        config['position'] = values['position']
        config.pop('width' if not vertical else 'height', None)
        config['width' if vertical else 'height'] = values['thickness']
        # Only the outer edge and bar ends need screen padding. An inward
        # margin also enlarges the compositor's reserved area above the tiles.
        inward = {'bottom': 'top', 'top': 'bottom', 'left': 'right', 'right': 'left'}[values['position']]
        for side in ('top', 'bottom', 'left', 'right'):
            config['margin-' + side] = 0 if side == inward or values['panel_mode']=='docked' else 8
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
    # A single root surface or content-sized occupied segments share the material.
    base=values['surface_color'] or options.get('_surface_background') or '@surface_container_high'
    radius=options.get('_surface_radius','12px')
    material={
        'solid': f'background-color: {base}; background-image: none;',
        'mica': f'background-color: alpha({base}, 0.90); background-image: linear-gradient(135deg, alpha(@primary, 0.13), alpha({base}, 0.04));',
        'acrylic': f'background-color: alpha({base}, 0.66); background-image: repeating-linear-gradient(120deg, alpha(@on_surface, 0.018) 0px, alpha(@on_surface, 0.018) 1px, transparent 1px, transparent 3px);',
        'candy': f'background-color: alpha({base}, 0.82); background-image: linear-gradient(to bottom, alpha(@on_surface, 0.24), alpha(@primary, 0.18) 48%, alpha({base}, 0.12) 51%, alpha(@primary, 0.09));',
    }[values['panel_material']]
    selector='window#waybar.adws-panel > box'
    # Specificity exceeds appearance overrides; explicit colors remain the base.
    lines.append(f'{selector} {{ {material} }}')
    segment='window#waybar.adws-panel.adws-split > box > box'
    lines.append(f'window#waybar.adws-panel.adws-split > box {{ background:transparent; border:none; box-shadow:none; }}')
    lines.append(f'{segment} {{background:transparent; border:none; box-shadow:none; min-width:0; min-height:0;}}')
    parts = str(radius).split()
    tl, tr, br, bl = (parts * 4)[:4] if len(parts) in (1,2,4) else [parts[0],parts[1],parts[2],parts[1]]
    vertical = values['position'] in ('left','right')
    pointed = values['split_center_corners'] == 'pointed'
    # Every end facing a split gap is pointed, including a two-segment bar
    # with an empty center. Only the outward ends retain the configured radius.
    tip_inset = values['thickness'] / 2 + 5
    pointed_radii = {
        'left': f'{tl} {tr} 0 0' if vertical else f'{tl} 0 0 {bl}',
        'right': f'0 0 {br} {bl}' if vertical else f'0 {tr} {br} 0',
        'center': '0',
    }
    for slot in options.get('_occupied_slots', ('left','center','right')):
        if slot not in ('left','center','right'): continue
        front = tip_inset if pointed and slot != 'left' else 5
        back = tip_inset if pointed and slot != 'right' else 5
        padding = f'{front:g}px 0 {back:g}px 0' if vertical else f'0 {back:g}px 0 {front:g}px'
        corners = pointed_radii[slot] if pointed else radius
        lines.append(f'{segment}.modules-{slot} {{ {material} border-radius:{corners}; padding:{padding}; }}')
    # Docking squares only the screen-facing ends; the clipped inward tips
    # remain intact. Rounded mode retains the original inward radii.
    lines.append('window#waybar.adws-panel.adws-docked > box { border-radius:0; }')
    docked = {
        'left': f'0 0 {br} {bl}' if vertical else f'0 {tr} {br} 0',
        'right': f'{tl} {tr} 0 0' if vertical else f'{tl} 0 0 {bl}',
        'center': radius,
    }
    for slot in options.get('_occupied_slots', ('left','center','right')):
        if slot not in docked: continue
        corners = '0' if pointed else docked[slot]
        lines.append(f'window#waybar.adws-panel.adws-split.adws-docked > box > box.modules-{slot} {{border-radius:{corners};}}')
    return '\n'.join(lines)


def surface_from_css(text):
    """Carry appearance settings into generated surfaces without resetting manual colors."""
    result={}
    text=re.sub(r'/\*.*?\*/','',text,flags=re.S)
    for block in re.findall(r'window#waybar\s*>\s*box\s*\{([^}]*)\}',text,re.S):
        background=re.search(r'background(?:-color)?\s*:\s*([^;{}]+);',block)
        radius=re.search(r'border-radius\s*:\s*([0-9.]+(?:px|em|rem)?(?:\s+[0-9.]+(?:px|em|rem)?){0,3})\s*;',block)
        if background: result['_surface_background']=background.group(1).strip()
        if radius: result['_surface_radius']=radius.group(1).strip()
    return result

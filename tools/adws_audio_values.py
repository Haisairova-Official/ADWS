"""Pure audio endpoint and level helpers shared by settings and taskbar."""
import math

def usable_device(device):
    """Hide PulseAudio/PipeWire dummy endpoints without hiding real virtual routes."""
    name = str(device.get('name') or '').lower()
    description = str(device.get('description') or '').strip().lower()
    driver = str(device.get('driver') or '').lower()
    props = device.get('properties') or {}
    factory = str(props.get('factory.name') or '').lower()
    return not (description in ('null', '(null)') or name.endswith('.monitor') or name in ('null', 'auto_null', 'null-sink', 'null_sink')
                or 'module-null-sink' in driver or 'module-null-source' in driver
                or factory in ('support.null-audio-sink', 'support.null-audio-source'))


def volume_percent(item):
    levels = []
    for value in item.get('volume', {}).values():
        try:
            level = float(value.get('value', 0)) / 65536 * 100
            if math.isfinite(level): levels.append(max(0, level))
        except (TypeError, ValueError, AttributeError): pass
    return max(levels, default=0)

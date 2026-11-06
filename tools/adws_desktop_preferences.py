"""Shared ADWS desktop output preference (independent of menu placement)."""
import json
import os
from pathlib import Path
import tempfile


def path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/desktop.json'


def load():
    try:
        value = json.loads(path().read_text())
        if isinstance(value, dict) and isinstance(value.get('default_monitor'), str):
            return value
    except (OSError, ValueError):
        pass
    return {'default_monitor': 'primary'}


def save(monitor, connector='', label=''):
    if not isinstance(monitor, str) or not monitor:
        raise ValueError('Invalid default monitor')
    value = load()
    value.update(default_monitor=monitor, connector=connector, label=label)
    _write(value)


def widgets_visible():
    return load().get('widgets_visible', True) is not False


def save_widgets_visibility(visible):
    value = load()
    value['widgets_visible'] = bool(visible)
    _write(value)


def _write(value):
    destination = path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.desktop-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def choose(views, system_monitor=None, preference=None):
    requested = (preference or load())['default_monitor']
    # A disconnected stable identity must not select a different screen that
    # happens to reuse its connector. Legacy connector-only values still work.
    selected = next((view for view in views if requested in
                     (view.monitor_key, getattr(view, 'connector_key', view.monitor_key))), None)
    if selected is not None:
        return selected
    selected = next((view for view in views if view.monitor == system_monitor), None)
    return selected or min(views, key=lambda view: (view.monitor.get_geometry().x,
                                                   view.monitor.get_geometry().y), default=None)

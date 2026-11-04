"""Independent host components delivered in one versioned .mplg package."""
import copy
import re

HOSTS = ('taskbar', 'desktop')
LOCAL_ID = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')


def components(manifest, target=None):
    """Legacy entries remain taskbar-only; desktop entries are always explicit."""
    if target is not None and target not in HOSTS:
        raise ValueError('Unknown component host')
    base = {k: copy.deepcopy(v) for k, v in manifest.items() if k != 'components'}
    result = []
    if base.get('entry'):
        legacy = copy.deepcopy(base)
        legacy['target'] = 'taskbar'
        result.append(legacy)
    declared = manifest.get('components', [])
    if not isinstance(declared, list) or len(declared) > 32:
        raise ValueError('components must be an array of at most 32 entries')
    seen = set()
    for item in declared:
        if not isinstance(item, dict):
            raise ValueError('Component must be an object')
        key, host = item.get('id'), item.get('target')
        if not isinstance(key, str) or not LOCAL_ID.fullmatch(key) or key in seen:
            raise ValueError('Component IDs must be unique local identifiers')
        if host not in HOSTS:
            raise ValueError('Component target must be desktop or taskbar')
        seen.add(key)
        value = {**copy.deepcopy(base), **copy.deepcopy(item)}
        # Package identity/version cannot be overridden by a child component.
        value.update(id=manifest.get('id', '') + '.' + key,
                     version=manifest.get('version'), packageId=manifest.get('id'),
                     componentId=key, target=host)
        result.append(value)
    return [value for value in result if target is None or value['target'] == target]


def select(manifest, component=None):
    candidates = components(manifest)
    if component is None:
        legacy = next((v for v in candidates if 'componentId' not in v), None)
        if legacy is not None:
            return legacy
        if len(candidates) == 1:
            return candidates[0]
        raise ValueError('Choose a component from this package')
    value = next((v for v in candidates if v.get('componentId') == component), None)
    if value is None:
        raise ValueError('Component not found in package')
    return value

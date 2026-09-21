"""Public Plugin API 1 normalization, schema validation and package translations."""
import copy
import json
import math
import re
from pathlib import PurePosixPath, Path
from adws_i18n import chinese
from adws_update import version_key, current_version

ID = re.compile(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+')
TYPES = {'string', 'number', 'boolean', 'choice', 'color', 'font', 'url'}
CONTROLS = {'play-pause', 'previous', 'next'}
ALIASES = {'org.adws.neteaselyrics': 'org.AkiACG_Community.NCMLyricsBar'}


def canonical_id(value):
    return ALIASES.get(value, value)


def package_version(value):
    core, _, pre = value.split('+')[0].partition('-')
    numbers = tuple(int(part) for part in core.split('.'))
    return numbers, not bool(pre), tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split('.'))


def safe_path(value):
    return (isinstance(value, str) and bool(value) and '\\' not in value
            and not value.startswith('/') and ':' not in value
            and all(p not in ('', '.', '..') for p in value.rstrip('/').split('/')))


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def schema_errors(schema):
    if not isinstance(schema, list):
        return ['settingsSchema must be an array']
    errors, keys = [], set()
    for field in schema:
        if not isinstance(field, dict):
            errors.append('Each setting must be an object'); continue
        key, kind = field.get('key'), field.get('type')
        if not isinstance(key, str) or not key or key in keys:
            errors.append('Setting keys must be unique nonempty strings'); continue
        keys.add(key)
        if not isinstance(kind, str) or kind not in TYPES:
            errors.append(f'Unsupported setting type: {kind}'); continue
        for caption in ('label', 'hint'):
            if caption in field and not isinstance(field[caption], str): errors.append(f'{key}.{caption} must be a string')
        value = field.get('default')
        if kind == 'number':
            low, high, step = field.get('min', 0), field.get('max', 100), field.get('step', 1)
            if not all(finite(x) for x in (low, high, step)) or low > high or step <= 0:
                errors.append(f'Invalid numeric range: {key}')
            elif 'default' in field and (not finite(value) or not low <= value <= high): errors.append(f'Invalid numeric default: {key}')
        elif kind == 'boolean':
            if 'default' in field and not isinstance(value, bool): errors.append(f'Invalid boolean default: {key}')
        elif kind == 'choice':
            choices = field.get('choices')
            if not isinstance(choices, list) or not choices or not all(isinstance(c, list) and len(c) == 2 and all(isinstance(s, str) for s in c) for c in choices):
                errors.append(f'Invalid choices: {key}')
            elif len({c[0] for c in choices}) != len(choices) or ('default' in field and value not in [c[0] for c in choices]): errors.append(f'Invalid choice default or duplicate choice: {key}')
        elif 'default' in field and not isinstance(value, str): errors.append(f'Invalid string default: {key}')
    return errors


def normalize(manifest):
    result = copy.deepcopy(manifest)
    if 'renderer' in result:
        result.update(api='adws-plugin', apiVersion=1, kind='panel', language='python')
        result['interfaces'] = ['panel.rows-v1' if result['renderer'] == 'panel.rows-v1' else 'panel.json-v1']
    return result


def public_errors(manifest):
    errors = []
    if manifest.get('renderer') not in ('panel.text-v1', 'panel.rows-v1'): errors.append('Unsupported renderer')
    host = manifest.get('adws', {})
    if not isinstance(host, dict): return errors + ['adws must be an object']
    if type(host.get('api', 1)) is not int or host.get('api', 1) != 1: errors.append('Unsupported Plugin API version')
    try:
        minimum = host.get('minVersion', '1.25')
        required, current = version_key(minimum), version_key(current_version())
        # A bare minimum specifies the compatible version family, including its preview.
        if re.fullmatch(r'v?\d+\.\d+(?:\.\d+)?', minimum):
            required, current = required[:2], current[:2]
        if required > current: errors.append('ADWS version is below minVersion')
    except (ValueError, TypeError, AttributeError): errors.append('Invalid minVersion')
    if 'language' in manifest and manifest['language'] != 'python': errors.append('Plugin API 1 supports Python entries only')
    controls = manifest.get('controls', [])
    if (not isinstance(controls, list) or not all(isinstance(control, str) for control in controls)
            or len(set(controls)) != len(controls)
            or any(control not in CONTROLS for control in controls)):
        errors.append('Invalid controls')
    defaults = manifest.get('defaults', {})
    if isinstance(defaults, dict):
        for key in ('width', 'interval'):
            if key in defaults and (not finite(defaults[key]) or defaults[key] < 0): errors.append(f'Invalid defaults.{key}')
        if 'align' in defaults and (not finite(defaults['align']) or not 0 <= defaults['align'] <= 1): errors.append('Invalid defaults.align')
    return errors


def localized(manifest, archive):
    result = normalize(manifest)
    name = 'locale/zh.json' if chinese() else 'locale/en.json'
    try:
        table = json.loads(archive.read(name).decode('utf-8'))
    except KeyError:
        table = {}
    if not isinstance(table, dict) or any(not isinstance(v, str) for v in table.values()):
        raise ValueError('Plugin locale must be an object of strings')
    def tr(value): return table.get(value, value)
    for key in ('name', 'description'):
        if isinstance(result.get(key), str): result[key] = tr(result[key])
    for field in result.get('settingsSchema', []):
        for key in ('label', 'hint'):
            if key in field: field[key] = tr(field[key])
        if field.get('type') == 'choice': field['choices'] = [[key, tr(label)] for key, label in field['choices']]
    return result


def settings(manifest, overrides):
    if not isinstance(overrides, dict): raise ValueError('Settings must be a JSON object')
    values = {}
    for field in manifest.get('settingsSchema', []):
        kind = field['type']
        fallback = False if kind == 'boolean' else field.get('min', 0) if kind == 'number' else field['choices'][0][0] if kind == 'choice' else ''
        values[field['key']] = field.get('default', fallback)
    values.update(overrides)
    for field in manifest.get('settingsSchema', []):
        value, kind = values[field['key']], field['type']
        valid = (isinstance(value, bool) if kind == 'boolean' else
                 finite(value) and field.get('min', 0) <= value <= field.get('max', 100) if kind == 'number' else
                 value in [c[0] for c in field['choices']] if kind == 'choice' else isinstance(value, str))
        if not valid: raise ValueError(f'Invalid setting: {field["key"]}')
    return values

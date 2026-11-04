"""Stable output identity shared by display profiles and desktop surfaces."""
import hashlib
import json


def description(output):
    parts = [str(output.get(key) or '').strip() for key in ('make', 'model', 'serial')]
    # Niri spells an unavailable serial as "Unknown" in output selectors.
    return ' '.join((parts[0] or 'Unknown', parts[1] or 'Unknown', parts[2] or 'Unknown'))


def assign(outputs):
    counts = {}
    for item in outputs:
        selector = description(item)
        counts[selector.casefold()] = counts.get(selector.casefold(), 0) + 1
    for item in outputs:
        selector = description(item)
        identifiable = bool(item.get('make') or item.get('model'))
        serial = str(item.get('serial') or '').strip().casefold()
        unique = identifiable and serial not in ('', 'unknown', 'none', '0', '000000') and counts[selector.casefold()] == 1
        item['selector'] = selector if unique else item['name']
        # Connector fallback is explicit, never silently swap identical monitors.
        item['identity_ambiguous'] = not unique
        payload = ['monitor', selector.casefold()] if unique else ['connector', item['name'], selector.casefold()]
        item['monitor_id'] = hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:24]
    return outputs


def resolve(saved, outputs):
    matches = [item for item in outputs if item.get('monitor_id') == saved]
    if len(matches) == 1:
        return matches[0]
    # Migration from the old connector-keyed desktop layout.
    return next((item for item in outputs if item['name'] == saved), None)

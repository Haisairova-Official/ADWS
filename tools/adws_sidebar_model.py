"""Persistent, bounded dashboard state independent of the GTK presentation."""
import math
import time

CATALOG = {
    'sound': ('声音', 'audio-volume-high-symbolic', 1),
    'brightness': ('亮度', 'display-brightness-symbolic', 1),
    'media': ('媒体播放', 'audio-x-generic-symbolic', 2),
    'system': ('系统监视', 'utilities-system-monitor-symbolic', 2),
    'notes': ('便签', 'accessories-text-editor-symbolic', 2),
    'calendar': ('日历', 'x-office-calendar-symbolic', 2),
    'todo': ('待办', 'view-list-symbolic', 2),
    'timer': ('计时器', 'alarm-symbolic', 1),
}
DEFAULT_ORDER = ['sound', 'brightness', 'media', 'system', 'notes']


def normalize_board(value):
    if not isinstance(value, dict): value = {}
    raw = value.get('order', DEFAULT_ORDER)
    if not isinstance(raw, list): raw = DEFAULT_ORDER
    order = list(dict.fromkeys(item for item in raw if isinstance(item, str) and item in CATALOG))
    sizes = value.get('sizes', {})
    if not isinstance(sizes, dict): sizes = {}
    return {'order': order, 'sizes': {key: sizes.get(key) if type(sizes.get(key)) is int and sizes[key] in (1, 2) else CATALOG[key][2] for key in CATALOG}}


def placements(board, columns=2):
    row, col = 0, 0
    result = []
    for key in board['order']:
        span = min(columns, board['sizes'][key])
        if col+span > columns: row += 1; col = 0
        result.append((key, col, row, span))
        col += span
        if col == columns: row += 1; col = 0
    return result


def move_card(board, key, before):
    order = list(board['order'])
    if key not in order or before not in order or key == before: return order
    order.remove(key); order.insert(order.index(before), key)
    return order


def normalized_tasks(value):
    if not isinstance(value, list): return []
    return [{'text': item['text'][:256], 'done': item.get('done') is True} for item in value[:100]
            if isinstance(item, dict) and isinstance(item.get('text'), str) and item['text'].strip()]


def timer_remaining(value, now=None):
    if not isinstance(value, dict): return 0
    now = time.time() if now is None else now
    deadline = value.get('deadline')
    if type(deadline) in (float, int) and math.isfinite(deadline):
        return max(0, min(86400, math.ceil(deadline-now)))
    remaining = value.get('remaining', 1500)
    return max(0, min(86400, int(remaining))) if type(remaining) in (int,float) and math.isfinite(remaining) else 1500

"""MNWS UI language: Chinese locales use Chinese, all others use English."""
from functools import lru_cache
import json
import os
import math
import random
from pathlib import Path


def chinese(environ=None):
    env = os.environ if environ is None else environ
    locale = env.get('LC_ALL') or env.get('LC_MESSAGES') or env.get('LANG') or 'C'
    if locale.split('.')[0].upper() in ('C', 'POSIX'):
        return False
    language = (env.get('LANGUAGE') or locale).split(':')[0]
    return language.lower().startswith('zh')


@lru_cache(maxsize=1)
def catalogue():
    path = Path(__file__).resolve().parents[3] / 'language/en.json'
    return json.loads(path.read_text(encoding='utf-8'))


def tr(message):
    if chinese():
        return message
    translated = catalogue().get(message, message)
    return translated if isinstance(translated, str) else message


def message(key, *, rng=None):
    """Select localized UI copy; weights live entirely in the language file."""
    if chinese():
        path = Path(__file__).resolve().parents[3] / 'language/zh.json'
        messages = json.loads(path.read_text(encoding='utf-8')).get('_messages', {})
    else:
        messages = catalogue().get('_messages', {})
    variants = messages[key]
    if isinstance(variants, str):
        return variants
    if not isinstance(variants, list) or not variants:
        raise ValueError(f'Invalid message variants: {key}')
    total = 0.0
    for variant in variants:
        weight = variant.get('weight')
        if not isinstance(variant.get('text'), str) or not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or weight <= 0:
            raise ValueError(f'Invalid message weight/text: {key}')
        total += weight
    if not math.isfinite(total):
        raise ValueError(f'Invalid total message weight: {key}')
    point = (rng or random).random() * total
    for variant in variants:
        point -= variant['weight']
        if point < 0:
            return variant['text']
    return variants[-1]['text']


def prepare_gtk_language():
    # GTK stock buttons must follow the same two-language policy as MNWS labels.
    if not chinese():
        os.environ['LANGUAGE'] = 'en'

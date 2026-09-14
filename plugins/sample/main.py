"""Minimal Plugin API 1: one JSON record per invocation."""
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument('--settings-json', default='{}')
args = parser.parse_args()
settings = json.loads(args.settings_json)
print(json.dumps({'text': settings.get('greeting', 'Hello MNWS') if settings.get('enabled', True) else '',
                  'tooltip': 'HelloWorld sample'}, ensure_ascii=False), flush=True)

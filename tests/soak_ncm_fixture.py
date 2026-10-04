"""Synthetic playback using NCMLyricsBar's real render() protocol (no network)."""
import importlib.util
import json
from pathlib import Path
import time

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ncm_soak', root / 'plugins/netease-lyrics/main.py')
lyrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lyrics)
started = time.monotonic()
previous = None
last_emit = 0.0
index = 0
while True:
    elapsed = time.monotonic() - started
    paused = 20 <= elapsed < 55
    if not paused:
        index += 1
    primary = ('中文歌词 English 日本語 ' * (index % 5 + 1)) + str(index)
    secondary = '' if index % 3 == 0 else 'Translation / 翻译 ' + str(index)
    track = {'title': 'Compatibility test', 'artists': ['ADWS'],
             'status': 'Paused' if paused else 'Playing', 'position': 1.0}
    payload = lyrics.render(track, {'state': 'ready', 'lines': [(0., primary)],
                                   'translation': [(0., secondary)]})
    record = json.dumps(payload, ensure_ascii=False)
    if record != previous or elapsed - last_emit >= 15:
        print(record, flush=True)
        previous, last_emit = record, elapsed
    time.sleep(.05)

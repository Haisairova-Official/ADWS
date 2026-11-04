"""Source-preserving Niri output configuration and independent preview recovery."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from adws_vm_mode import tokens, parse_nodes, decode_string
from adws_i18n import tr

FIELDS = {'mode', 'scale', 'transform', 'position'}


def config_tree(path):
    files, nodes, visiting = {}, {}, set()
    def read(path):
        path = Path(os.path.abspath(path))
        if path in visiting:
            raise ValueError(tr('显示配置存在循环引用。'))
        if path in files:
            return
        visiting.add(path)
        text = path.read_text()
        files[path] = text
        nodes[path] = parse_nodes(tokens(text))
        for node in nodes[path]:
            if node.disabled or node.name != 'include':
                continue
            quoted = [t for t in node.header if t.kind in ('quoted', 'string')]
            if len(quoted) != 1:
                raise ValueError(tr('无法识别显示配置的 include 路径。'))
            child = Path(decode_string(quoted[0])).expanduser()
            child = child if child.is_absolute() else path.parent / child
            optional = 'optional' in [t.value for t in node.header]
            if child.exists() or not optional:
                read(child)
        visiting.remove(path)
    read(path)
    return files, nodes


def compose(files, nodes, monitors, root):
    from adws_display import validate, TRANSFORMS
    edits = {path: [] for path in files}
    matches = {}
    for monitor in monitors:
        validate(monitor)
        matches[monitor['name'].casefold()] = monitor
        matches[monitor.get('selector', monitor['name']).casefold()] = monitor
    extras = {m['name']: [] for m in monitors}
    for path, entries in nodes.items():
        for node in entries:
            if node.disabled or node.name != 'output' or not node.header:
                continue
            name = decode_string(node.header[0]).casefold()
            monitor = matches.get(name)
            if monitor is None:
                continue
            # Keep unrelated output settings (VRR, color, startup focus, etc.).
            for child in node.children:
                if child.disabled or child.name not in FIELDS:
                    extras[monitor['name']].append(files[path][child.start:child.end])
            edits[path].append((node.start, node.end, '// Display settings managed by ADWS'))
    blocks = []
    for monitor in monitors:
        extra = '\n'.join('    '+line for line in extras[monitor['name']])
        blocks.append('output ' + json.dumps(monitor.get('selector', monitor['name']), ensure_ascii=False) + ' {\n'
                      f'    mode "{monitor["mode"]}"\n    scale {float(monitor["scale"]):g}\n'
                      f'    transform "{TRANSFORMS[monitor["transform"]]}"\n'
                      f'    position x={monitor["x"]} y={monitor["y"]}\n' + extra + '\n}\n')
    result = {}
    for path, original in files.items():
        text = original
        for start, end, replacement in sorted(edits[path], reverse=True):
            text = text[:start]+replacement+text[end:]
        result[path] = text
    # Keep a single managed block in the main config, so old Niri without
    # include support can also use this. User includes remain at original paths.
    begin, end = '// ADWS displays BEGIN', '// ADWS displays END'
    text = result[root]
    if begin in text or end in text:
        if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) > text.index(end):
            raise ValueError(tr('ADWS 显示配置标记不完整。'))
        a, b = text.index(begin), text.index(end)+len(end)
        # Retain profiles for disconnected screens from the prior managed block.
        previous = text[a+len(begin):text.index(end)]
        retained = [previous[node.start:node.end] for node in parse_nodes(tokens(previous)) if node.name == 'output']
        blocks = [part+'\n' for part in retained] + blocks
        text = text[:a]+text[b:]
    result[root] = text.rstrip()+'\n\n'+begin+'\n'+''.join(blocks)+end+'\n'
    return result


def validate_bundle(files, root, directory):
    copies = {path: directory/(hashlib.sha256(str(path).encode()).hexdigest()+'.kdl') for path in files}
    for path, content in files.items():
        edits = []
        for node in parse_nodes(tokens(content)):
            if node.disabled or node.name != 'include':
                continue
            token = next(t for t in node.header if t.kind in ('quoted','string'))
            child = Path(decode_string(token)).expanduser()
            child = Path(os.path.abspath(child if child.is_absolute() else path.parent/child))
            # Optional absent includes must remain absent in the validation tree.
            target = copies.get(child, child)
            edits.append((token.start, token.end, json.dumps(str(target))))
        for start, end, replacement in sorted(edits, reverse=True):
            content = content[:start]+replacement+content[end:]
        copies[path].write_text(content)
    result = subprocess.run(['niri','validate','-c',str(copies[root])], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError(tr('显示配置验证失败，未修改配置：')+(result.stderr or result.stdout)[-4000:])


def persist(monitors, path=None):
    from adws_windows import config_path
    from adws_atomic import replace_files
    root = Path(os.path.abspath(path or config_path()))
    files, nodes = config_tree(root)
    updated = compose(files, nodes, monitors, root)
    with tempfile.TemporaryDirectory(prefix='adws-display-check-') as folder:
        validate_bundle(updated, root, Path(folder))
    if any(path.read_text() != original for path, original in files.items()):
        raise ValueError(tr('显示配置已被其他程序修改，请重试。'))
    changes = {path: text.encode() for path, text in updated.items() if text != files[path]}
    if not changes:
        return
    # Backups stay with Niri, outside removable ADWS configuration.
    backup = root.parent/('.adws-display-backup-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(3).hex())
    backup.mkdir(mode=0o700)
    manifest = {}
    for index, path in enumerate(changes):
        name = f'{index}.kdl'
        shutil.copy2(path, backup/name)
        manifest[str(path)] = name
    (backup/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    replace_files(changes)


class PreviewGuard:
    def __init__(self, session, old):
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--guard'],
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        self.process.stdin.write(json.dumps({'session':session,'old':old})+'\n')
        self.process.stdin.flush()

    def finish(self, keep=False):
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.write('keep\n' if keep else 'restore\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            self.process.stdin.close()


def guard_main():
    import select
    from adws_display import restore_all
    payload = json.loads(sys.stdin.readline())
    # Bounded even if the GUI is stuck; EOF also restores after GUI crashes.
    ready, _, _ = select.select([sys.stdin], [], [], 45)
    answer = sys.stdin.readline().strip() if ready else ''
    if answer != 'keep':
        restore_all(payload['session'], payload['old'])


if __name__ == '__main__' and sys.argv[1:] == ['--guard']:
    guard_main()

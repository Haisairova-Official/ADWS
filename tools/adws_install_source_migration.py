"""Preserve a registered desktop's runtime state when installing at a new path.

The service currently uses state below its installation root. Only those known
runtime files are copied, after the outer transaction has stopped the desktop.
Personal XDG configuration stays in place; arbitrary old-source resources are
never moved or rewritten implicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

SCHEMA = 1
STATE_RELATIVE = Path('src/niri-desktop-layer/state')
STATE_NAMES = ('layout.json', 'desktop-groups.json')
MAX_STATE_BYTES = 16 * 1024 * 1024


def _exists(path):
    return path.exists() or path.is_symlink()


def _safe_path(path):
    """Never follow a state-file link or a link in its parent directories."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink(): raise ValueError('State path needs symlink review: ' + str(part))
    return path


def _bytes(path):
    path = _safe_path(path)
    if not _exists(path): return None
    if not stat.S_ISREG(path.stat().st_mode): raise ValueError('State must be a regular file: ' + str(path))
    if path.stat().st_size > MAX_STATE_BYTES: raise ValueError('Desktop state is too large: ' + str(path))
    with path.open('rb') as stream: data = stream.read(MAX_STATE_BYTES + 1)
    if len(data) > MAX_STATE_BYTES: raise ValueError('Desktop state is too large: ' + str(path))
    return data


def _digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _state(path, old_root):
    raw = _bytes(path)
    if raw is None: return None
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Unsupported desktop state: ' + str(path))
    if path.name == 'desktop-groups.json':
        from adws_desktop_groups_model import validate
        validate(value)
        # A selected picture/folder elsewhere in the user's home remains valid.
        # An asset inside the old installation needs its own reviewed migration.
        for group in value['groups']:
            for field in ('directory', 'background_image'):
                name = group.get(field)
                if name and Path(name).expanduser().resolve().is_relative_to(old_root):
                    raise ValueError('Desktop group resource in old installation needs review: ' + field + '=' + name)
    elif not isinstance(value.get('positions'), dict) or not isinstance(value.get('preferences', {}), dict):
        raise ValueError('Invalid desktop layout: ' + str(path))
    return raw


def running_desktops():
    """Read only current-user desktop argv; never collect session credentials."""
    from adws_runtime import pids
    rows = []
    for pid in pids('desktop'):
        try:
            argv = [os.fsdecode(v) for v in (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0') if v]
        except FileNotFoundError: continue
        rows.append({'pid': pid, 'argv': argv})
    return rows


def _check_runtime(rows, root, *, stopped=False):
    if stopped and rows: raise ValueError('Desktop must stop before copying final runtime state')
    expected_script = root/'src/niri-desktop-layer/desktop-layer'
    expected_state = root/STATE_RELATIVE/'layout.json'
    for row in rows:
        argv = row.get('argv', [])
        if not argv: raise ValueError('Desktop launch command could not be inspected')
        start = 1 if Path(argv[0]).name.startswith('python') else 0
        if len(argv) <= start or not Path(argv[start]).is_absolute() or Path(argv[start]).resolve() != expected_script:
            raise ValueError('Running desktop does not belong to the registered installation')
        paths = []
        for i, arg in enumerate(argv[start+1:], start+1):
            if arg == '--state':
                if i+1 >= len(argv): raise ValueError('Desktop --state has no path')
                paths.append(argv[i+1])
            elif arg.startswith('--state='): paths.append(arg.split('=', 1)[1])
        if len(paths) != 1 or not Path(paths[0]).is_absolute() or Path(paths[0]).resolve() != expected_state:
            raise ValueError('Custom or implicit desktop --state requires an explicit migration review')


def _unknown_files(folder):
    _safe_path(folder)
    if not _exists(folder): return []
    if not folder.is_dir(): raise ValueError('Desktop state directory is not a directory: ' + str(folder))
    return sorted(str(path) for path in folder.iterdir() if path.name not in STATE_NAMES)


def plan(root, *, state_home=None, runtime=None):
    """Return a read-only proposal. Runtime contents may change until stop.

    ``source_hashes`` contains only the static inventory. The approved source
    file paths, schema and resource boundaries are rechecked after stop; this
    deliberately preserves legitimate final icon moves made during installation.
    """
    root = Path(root).expanduser().resolve()
    state = Path(state_home or os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state').expanduser().absolute()
    inventory = state/'adws/install-record.json'
    result = {'schema_version': SCHEMA, 'root': str(root), 'previous_root': None,
              'inventory_path': str(inventory), 'files': [], 'conflicts': [],
              'source_hashes': {}, 'snapshot_targets': [], 'status': 'none',
              'policy': 'Copy only registered desktop runtime state after stop; retain original source and all XDG personal configuration.'}
    try:
        data = _bytes(inventory)
        result['source_hashes'][str(inventory)] = _digest(data)
        record = json.loads(data) if data is not None else {}
        if not isinstance(record, dict): raise ValueError('Invalid ADWS install inventory')
        previous = record.get('root')
        rows = running_desktops() if runtime is None else runtime
        if not previous:
            if rows: _check_runtime(rows, root)
            return result
        if not isinstance(previous, str) or not Path(previous).is_absolute():
            raise ValueError('Registered installation root must be an absolute path')
        old = Path(previous).resolve()
        result['previous_root'] = str(old)
        if old == root: return result
        _check_runtime(rows, old)
        if not (old/'adws').is_file() or not (old/'src/niri-desktop-layer/desktop-layer').is_file():
            raise ValueError('Registered old installation is unavailable; review its saved desktop state before changing paths')
        source_dir, target_dir = old/STATE_RELATIVE, root/STATE_RELATIVE
        unknown = _unknown_files(source_dir)
        if unknown: raise ValueError('Unrecognized files in old desktop state require review: ' + ', '.join(unknown))
        _safe_path(target_dir)
        for name in STATE_NAMES:
            source, target = source_dir/name, target_dir/name
            source_data = _state(source, old)
            target_data = _bytes(target)
            if target_data is not None and source_data != target_data:
                raise ValueError('New installation already has different desktop state: ' + str(target))
            result['files'].append({'source': str(source), 'target': str(target),
                                    'source_present': source_data is not None,
                                    'target_sha256': _digest(target_data)})
        result['snapshot_targets'] = [str(target_dir)]
        result['status'] = 'ready'
    except (OSError, ValueError, TypeError) as exc:
        result['conflicts'].append({'kind': 'installation-source-migration', 'detail': str(exc)})
        result['status'] = 'blocked'
    return result


def verify_before(proposal, *, runtime=None, stopped=False):
    """Verify before transaction, then again after stop and before any writes."""
    if proposal.get('schema_version') != SCHEMA or proposal.get('conflicts'):
        raise ValueError('Installation source migration requires a new reviewed plan')
    for name, digest in proposal['source_hashes'].items():
        if _digest(_bytes(Path(name))) != digest:
            raise ValueError('Installation inventory changed after review: ' + name)
    if not proposal['files']: return True
    old, root = Path(proposal['previous_root']), Path(proposal['root'])
    _check_runtime(running_desktops() if runtime is None else runtime, old, stopped=stopped)
    unknown = _unknown_files(old/STATE_RELATIVE)
    if unknown: raise ValueError('Unreviewed desktop state appeared: ' + ', '.join(unknown))
    if {row['source'] for row in proposal['files']} != {str(old/STATE_RELATIVE/n) for n in STATE_NAMES}:
        raise ValueError('Invalid reviewed desktop state sources')
    for row in proposal['files']:
        source, target = Path(row['source']), Path(row['target'])
        if target != root/STATE_RELATIVE/source.name: raise ValueError('Invalid reviewed desktop state target')
        data = _state(source, old)
        if row['source_present'] and data is None: raise ValueError('Reviewed desktop state disappeared: ' + str(source))
        if _digest(_bytes(target)) != row['target_sha256']:
            raise ValueError('Desktop migration target changed after review: ' + str(target))
    return True


def apply(proposal, backup_dir, *, runtime=None):
    """Inside the configuration transaction, before install-record is rewritten.

    The caller includes snapshot_targets in its rollback. Originals are retained.
    The backup also records the exact final bytes actually copied, rather than a
    stale pre-stop hash. No live service or desktop content is manipulated here.
    """
    verify_before(proposal, runtime=runtime, stopped=True)
    if not proposal['files']: return {'status': 'unchanged', 'files': []}
    old = Path(proposal['previous_root'])
    backup = Path(backup_dir); backup.mkdir(parents=True, exist_ok=False)
    (backup/'plan.json').write_text(json.dumps(proposal, ensure_ascii=False, indent=2)+'\n')
    contents = {}
    for row in proposal['files']:
        raw = _state(Path(row['source']), old)
        if raw is not None:
            contents[Path(row['target'])] = raw
            saved = backup/Path(row['source']).name
            saved.write_bytes(raw); saved.chmod(0o600)
    # Recheck after reading both files. A restarted writer or user target edit
    # must not be hidden by the copy; outer transaction keeps its full snapshot.
    verify_before(proposal, runtime=runtime, stopped=True)
    for row in proposal['files']:
        raw = _state(Path(row['source']), old)
        if raw != contents.get(Path(row['target'])):
            raise ValueError('Desktop state changed while copying: ' + row['source'])
    from adws_atomic import stage
    staged = {}
    try:
        for target, raw in contents.items(): staged[target] = stage(target, raw, 0o600)
        verify_before(proposal, runtime=runtime, stopped=True)
        for row in proposal['files']:
            if _state(Path(row['source']), old) != contents.get(Path(row['target'])):
                raise ValueError('Desktop state changed while staging: ' + row['source'])
        for row in proposal['files']:
            target = Path(row['target'])
            temporary = staged.get(target)
            if temporary is None: continue
            # A brand-new destination uses an exclusive link to avoid replacing
            # an unreviewed file created concurrently in the final commit gap.
            if row['target_sha256'] is None:
                os.link(temporary, target); temporary.unlink()
            else:
                if _digest(_bytes(target)) != row['target_sha256']:
                    raise ValueError('Desktop migration target changed during copy: ' + str(target))
                os.replace(temporary, target)
    finally:
        for temporary in staged.values(): temporary.unlink(missing_ok=True)
    copied = [{'source': row['source'], 'target': row['target'], 'sha256': _digest(contents[Path(row['target'])])}
              for row in proposal['files'] if Path(row['target']) in contents]
    result = {'status': 'copied', 'backup': str(backup), 'files': copied,
              'previous_root': proposal['previous_root'], 'originals_retained': True}
    (backup/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result

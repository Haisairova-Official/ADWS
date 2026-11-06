"""Review legacy MNWS state before any new ADWS configuration is created.

Only unchanged, unambiguous configuration trees can be imported automatically.
Conversions of old commands, plugins or runtime state require a separate review;
they must never be hidden in the final configuration-deployment shell script.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil

SCHEMA = 1
ROOT = Path(__file__).resolve().parents[1]
LEGACY_REFERENCE = re.compile(r'(?<![A-Za-z0-9_])(?:mnws(?:-config|-layout)?)(?=[/\s."\'\\-]|$)')


def exists(path):
    return path.exists() or path.is_symlink()


def tree_manifest(path):
    """Content and permissions, including empty directories; no symlink traversal."""
    path = Path(path)
    if not path.is_dir() or path.is_symlink():
        raise ValueError('Legacy configuration must be a real directory: ' + str(path))
    result = {'.': {'kind': 'directory', 'mode': path.stat().st_mode & 0o777}}
    for item in sorted(path.rglob('*')):
        name = str(item.relative_to(path))
        if item.is_symlink(): raise ValueError('Legacy symlink needs review: ' + str(item))
        mode = item.stat().st_mode & 0o777
        if item.is_dir(): result[name] = {'kind': 'directory', 'mode': mode}
        elif item.is_file():
            with item.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            result[name] = {'kind': 'file', 'mode': mode, 'sha256': digest}
        else: raise ValueError('Legacy special file needs review: ' + str(item))
    return result


def plan(config_home, *, state_home=None, data_home=None, cache_home=None,
         niri_path=None, root=ROOT, home=None):
    """Pure pre-install proposal. No backups, moves, imports or processes."""
    home = Path(home or Path.home()).expanduser().absolute()
    config = Path(config_home).expanduser().absolute()
    folders = {
        'config': config,
        'state': Path(state_home or os.environ.get('XDG_STATE_HOME') or home/'.local/state').expanduser().absolute(),
        'data': Path(data_home or os.environ.get('XDG_DATA_HOME') or home/'.local/share').expanduser().absolute(),
        'cache': Path(cache_home or os.environ.get('XDG_CACHE_HOME') or home/'.cache').expanduser().absolute(),
    }
    result = {'schema_version': SCHEMA, 'config_home': str(config), 'root': str(Path(root).resolve()),
              'moves': [], 'conflicts': [], 'snapshot_targets': [], 'source_hashes': {},
              'legacy_paths': {kind: str(folder/'mnws') for kind, folder in folders.items()},
              'launcher_policy': None,
              'policy': 'Import unchanged config-only legacy tree before creating ADWS files; ambiguous conversions require separate review.'}
    for kind, folder in folders.items():
        source, target = folder/'mnws', folder/'adws'
        if not exists(source): continue
        if kind != 'config':
            result['conflicts'].append({'kind': 'legacy-'+kind+'-requires-review', 'source': str(source),
                'target': str(target), 'detail': 'Legacy plugins/runtime state cannot be assumed compatible; preserve and review separately.'})
            continue
        if exists(target):
            result['conflicts'].append({'kind': 'legacy-target-exists', 'source': str(source), 'target': str(target),
                'detail': 'Both configuration trees exist; neither may be displaced by automatic migration.'})
            continue
        try: manifest = tree_manifest(source)
        except (OSError, ValueError) as exc:
            result['conflicts'].append({'kind': 'legacy-tree-requires-review', 'source': str(source),
                                       'target': str(target), 'detail': str(exc)})
            continue
        if 'niri-session.kdl' in manifest:
            result['conflicts'].append({'kind': 'legacy-session-requires-review', 'source': str(source/'niri-session.kdl'),
                'target': str(target/'niri-session.kdl'), 'detail': 'Input environment must be reviewed against its future active contents.'})
        for name, entry in manifest.items():
            if entry['kind'] != 'file': continue
            item = source/name
            # These formats can hold old module names or executable paths.
            if item.suffix.lower() not in ('.json', '.jsonc', '.kdl', '.css', '.conf', '.ini', '.sh'): continue
            try: text = item.read_text()
            except (OSError, UnicodeError):
                result['conflicts'].append({'kind': 'legacy-unreadable-config', 'source': str(item), 'target': str(target/name)})
                continue
            if LEGACY_REFERENCE.search(text):
                result['conflicts'].append({'kind': 'legacy-reference-requires-conversion', 'source': str(item),
                    'target': str(target/name), 'detail': 'Old module names or executable paths require an explicitly reviewed conversion.'})
        result['moves'].append({'source': str(source), 'target': str(target), 'manifest': manifest})
        result['snapshot_targets'] += [str(source), str(target)]
        if 'taskbar-layout.json' in manifest:
            result['launcher_policy'] = {'policy': 'preserve', 'existing': [str(target/'taskbar-layout.json')],
                'description': '保留已审核旧配置中的开始按钮启动器与自定义命令。'}

    # Legacy starts may be present even when all XDG folders were moved before.
    # Read reachable includes using the common parser but never rewrite them.
    niri = Path(niri_path).expanduser() if niri_path else config/'niri/config.kdl'
    if niri.exists():
        from adws_install_session_config import niri_environment
        _, unknown, hashes = niri_environment(niri)
        result['source_hashes'].update(hashes)
        if result['moves'] and unknown:
            result['conflicts'].append({'kind': 'legacy-niri-includes-require-review', 'source': str(niri),
                                       'target': str(niri), 'detail': unknown})
        for name in hashes:
            text = Path(name).read_text()
            if LEGACY_REFERENCE.search(text):
                result['conflicts'].append({'kind': 'legacy-niri-command-requires-conversion', 'source': name,
                    'target': name, 'detail': 'Niri startup/rules still reference MNWS; do not change them after provider ownership review.'})
    for name in ('config-bottom.jsonc', 'style-bottom.css', 'modules.jsonc', 'colors.css'):
        path = config/'waybar'/name
        if not path.is_file(): continue
        raw = path.read_bytes(); result['source_hashes'][str(path)] = hashlib.sha256(raw).hexdigest()
        if LEGACY_REFERENCE.search(raw.decode('utf-8', errors='replace')):
            result['conflicts'].append({'kind': 'legacy-waybar-reference-requires-conversion', 'source': str(path),
                'target': str(path), 'detail': 'Legacy module/command conversion must be reviewed before the installation.'})
    result['status'] = 'blocked' if result['conflicts'] else 'ready' if result['moves'] else 'none'
    return result


def verify_before(proposal):
    if proposal.get('schema_version') != SCHEMA: raise ValueError('Unsupported legacy plan')
    if proposal['conflicts']: raise ValueError('Legacy migration requires review: ' + json.dumps(proposal['conflicts'], ensure_ascii=False))
    planned = {move['source'] for move in proposal['moves']}
    for name in proposal['legacy_paths'].values():
        if exists(Path(name)) and name not in planned:
            raise ValueError('Unreviewed legacy state appeared: ' + name)
    for name, digest in proposal['source_hashes'].items():
        if not Path(name).is_file() or hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError('Legacy-related configuration changed after review: ' + name)
    for move in proposal['moves']:
        source, target = Path(move['source']), Path(move['target'])
        if exists(target): raise ValueError('Legacy migration target appeared after review: ' + str(target))
        if tree_manifest(source) != move['manifest']: raise ValueError('Legacy source changed after review: ' + str(source))
    return True


def verify_applied(proposal):
    """Check the imported subset, permitting later ADWS-owned additions."""
    if proposal.get('schema_version') != SCHEMA or proposal['conflicts']:
        raise ValueError('Invalid or unresolved legacy plan')
    for name in proposal['legacy_paths'].values():
        if exists(Path(name)): raise ValueError('Unreviewed legacy state remains: ' + name)
    for move in proposal['moves']:
        current = tree_manifest(move['target'])
        if any(current.get(name) != item for name, item in move['manifest'].items()):
            raise ValueError('Imported legacy contents changed: ' + move['target'])
    return True


def apply(proposal, backup_dir):
    """Call at the start of the outer transaction, before any ADWS writes."""
    verify_before(proposal)
    if not proposal['moves']: return {'status': 'unchanged', 'moves': []}
    backup = Path(backup_dir); backup.mkdir(parents=True, exist_ok=False)
    (backup/'plan.json').write_text(json.dumps(proposal, ensure_ascii=False, indent=2)+'\n')
    for index, move in enumerate(proposal['moves']):
        source, target = Path(move['source']), Path(move['target'])
        # copytree creates the target exclusively, refusing a concurrently
        # created directory. Preserve the original in the transaction backup.
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        if tree_manifest(source) != move['manifest'] or tree_manifest(target) != move['manifest']:
            raise ValueError('Legacy configuration changed during import')
        shutil.move(str(source), str(backup/('source-'+str(index))))
    verify_applied(proposal)
    return {'status': 'imported', 'backup': str(backup), 'moves': proposal['moves']}


def initialize_managed_install(reviewed, *, root=ROOT):
    """No implicit moves/rewrites during the final deployment shell stage."""
    if not reviewed or reviewed.get('approved') is not True or 'legacy_plan' not in reviewed:
        raise ValueError('NEW_PLAN_REQUIRED: legacy configuration policy was not reviewed')
    proposal = reviewed['legacy_plan']
    if Path(root).resolve() != Path(reviewed['source_root']).resolve():
        raise ValueError('Legacy initialization source differs from reviewed installation')
    verify_applied(proposal)
    from adws_migrate import install_bundled_plugin
    messages = []
    install_bundled_plugin(Path(reviewed['data_home']), Path(root), messages)
    return messages

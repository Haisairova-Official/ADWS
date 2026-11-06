"""Versioned personal-environment migration with explicit review and rollback.

This module never executes imported scripts, enables services, changes accounts,
or imports monitor/GPU/session configuration. Callers must show the plan before
applying it. Shell files and application associations require per-file approval.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

SCHEMA_VERSION = 2
SUPPORTED_SCHEMAS = (1, 2)
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_FILES = 20000
MAX_TOTAL_BYTES = 512 * 1024 * 1024
# category, relative path, is directory, needs individual review
RULES = (
    ('shell', '.bashrc', False, True),
    ('shell', '.zshrc', False, True),
    ('shell', '.config/fish/config.fish', False, True),
    ('aliases', '.bash_aliases', False, True),
    ('aliases', '.config/fish/functions', True, True),
    ('themes', '.themes', True, False),
    ('themes', '.local/share/themes', True, False),
    ('themes', '.config/gtk-3.0/settings.ini', False, True),
    ('themes', '.config/gtk-4.0/settings.ini', False, True),
    ('plugins', '.local/share/adws/plugins', True, False),
    ('plugins', '.oh-my-zsh/custom/plugins', True, True),
    ('fonts', '.fonts', True, False),
    ('fonts', '.local/share/fonts', True, False),
    ('cursors', '.icons', True, False),
    ('cursors', '.local/share/icons', True, False),
    ('avatar', '.face', False, False),
    ('avatar', '.face.icon', False, False),
    ('defaults', '.config/mimeapps.list', False, True),
    ('defaults', '.local/share/applications/mimeapps.list', False, True),
    ('defaults', '.config/adws/default-terminal.json', False, True),
)
CATEGORIES = tuple(dict.fromkeys(rule[0] for rule in RULES)) + ('nickname',)
EXCLUDED = (
    '.config/niri', '.config/hypr', '.config/environment.d', '.pam_environment',
    '.profile', '.bash_profile', '.zprofile', '.config/autostart',
    '.config/systemd/user', '.config/adws/displays.json',
)
SESSION_ASSIGNMENT = re.compile(
    r'\b(?:DISPLAY|WAYLAND_DISPLAY|NIRI_SOCKET|XDG_SESSION\w*|GBM_BACKEND|'
    r'__GL\w*|WLR_\w*|NVIDIA\w*|QT_QPA_PLATFORM|GDK_BACKEND)\s*=')
SESSION_START = re.compile(r'(?:^|[;\n])\s*(?:exec\s+)?(?:niri|Hyprland|startx|startplasma-wayland)\b')


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Invalid migration path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or str(path) != value:
        raise ValueError('Migration path must be a normalized home-relative path: ' + value)
    return path


def _rule(relative):
    path = _relative(relative)
    for category, prefix, directory, review in RULES:
        if relative == prefix or directory and PurePosixPath(prefix) in path.parents:
            return category, review
    raise ValueError('Path is outside the personal-environment manifest: ' + relative)


def _safe(root, relative):
    path = root
    for part in _relative(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink migration is not supported: ' + relative)
    return path


def _roots(home, xdg=None, use_environment=False):
    home = Path(home).expanduser().resolve(strict=True)
    selected = dict(xdg or {})
    if set(selected) - {'config', 'data'}:
        raise ValueError('Unknown XDG migration location')
    if use_environment and home == Path.home().resolve():
        for name, variable in [('config', 'XDG_CONFIG_HOME'), ('data', 'XDG_DATA_HOME')]:
            if name not in selected and os.environ.get(variable): selected[name] = os.environ[variable]
    roots = {'home': str(home)}
    for name, default in [('config', home/'.config'), ('data', home/'.local/share')]:
        path = Path(selected.get(name, default)).expanduser()
        if not path.is_absolute(): raise ValueError('XDG migration roots must be absolute')
        roots[name] = str(path.resolve())
    return roots


def _location(roots, relative):
    _relative(relative)
    if relative.startswith('.config/'):
        key, rest = 'config', relative[len('.config/'):]
    elif relative.startswith('.local/share/'):
        key, rest = 'data', relative[len('.local/share/'):]
    else:
        key, rest = 'home', relative
    root = Path(roots[key])
    if not root.is_absolute(): raise ValueError('Invalid migration root')
    if root.is_symlink(): raise ValueError('Migration root became a symlink')
    return _safe(root, rest)


def source_path(plan, entry):
    relative = entry['path'] if isinstance(entry, dict) else entry
    return _location(plan.get('source_roots') or _roots(plan['source_home']), relative)


def destination_path(plan, entry):
    """Resolve a logical inventory path to the explicitly selected XDG target."""
    relative = entry['path'] if isinstance(entry, dict) else entry
    return _location(plan.get('target_roots') or _roots(plan['target_home']), relative)


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError('Not a regular file or migration size limit exceeded: ' + str(path))
        data = file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('Migration size limit exceeded: ' + str(path))
        return data, stat.S_IMODE(info.st_mode) & 0o777


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _blocked_shell(category, data):
    if category not in ('shell', 'aliases'):
        return False
    text = data.decode('utf-8', errors='replace')
    return bool(SESSION_ASSIGNMENT.search(text) or SESSION_START.search(text))


def inventory(source_home, source_xdg=None):
    """Read portable files and review-only entries; never read outside source home."""
    source = Path(source_home).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise ValueError('Source home is not a directory')
    roots = _roots(source, source_xdg)
    result = {'schema_version': SCHEMA_VERSION, 'source_home': str(source), 'source_roots': roots,
              'categories': list(CATEGORIES), 'files': [], 'excluded': [],
              'account': {'nickname': None, 'status': 'requires_account_service_selection'},
              'notes': ['No account/session caches, passwords, startup services, display or GPU settings are imported.',
                        'Default associations must be checked against installed target applications.',
                        'Shell files are copied only after individual approval; they are never executed by migration.']}
    for relative in EXCLUDED:
        try:
            path = _location(roots, relative)
            present = path.exists() or path.is_symlink()
        except ValueError:
            present = True
        if present:
            result['excluded'].append({'path': relative, 'reason': 'hardware_or_session_specific'})
    for category, relative, directory, review in RULES:
        logical_prefix = relative
        try:
            base = _location(roots, relative)
        except ValueError:
            result['excluded'].append({'path': relative, 'reason': 'symlink'})
            continue
        if not base.exists():
            continue
        candidates = []
        if directory:
            if not base.is_dir():
                result['excluded'].append({'path': relative, 'reason': 'expected_directory'})
                continue
            for folder, dirs, files in os.walk(base, followlinks=False):
                for name in list(dirs):
                    candidate = Path(folder) / name
                    if candidate.is_symlink():
                        result['excluded'].append({'path': (PurePosixPath(logical_prefix) / candidate.relative_to(base)).as_posix(), 'reason': 'symlink'})
                        dirs.remove(name)
                candidates.extend(Path(folder) / name for name in files)
                if len(candidates) + len(result['files']) > MAX_FILES:
                    raise ValueError('Personal-environment manifest exceeds file limit')
        else:
            candidates = [base]
        for candidate in sorted(candidates):
            relative = (PurePosixPath(logical_prefix) / candidate.relative_to(base)).as_posix() if directory else logical_prefix
            try:
                data, mode = _read(_location(roots, relative))
            except (OSError, ValueError) as error:
                result['excluded'].append({'path': relative, 'reason': str(error)})
                continue
            if _blocked_shell(category, data):
                result['excluded'].append({'path': relative, 'reason': 'contains_hardware_or_session_settings'})
                continue
            result['files'].append({'path': relative, 'category': category, 'review_required': review,
                                    'sha256': _digest(data), 'size': len(data), 'mode': mode})
    return result


def plan_migration(source_home, target_home, categories, approved_paths=None, overwrite_paths=(),
                   *, target_xdg=None, source_xdg=None, skipped_paths=()):
    """Create a reviewable plan. Existing differing files are preserved by default."""
    selected = set(categories)
    if selected - set(CATEGORIES):
        raise ValueError('Unknown migration categories: ' + ', '.join(sorted(selected - set(CATEGORIES))))
    approved = {_relative(p).as_posix() for p in approved_paths or ()}
    overwrite = {_relative(p).as_posix() for p in overwrite_paths}
    skipped = {_relative(p).as_posix() for p in skipped_paths}
    manifest = inventory(source_home, source_xdg)
    source = Path(manifest['source_home'])
    target = Path(target_home).expanduser().resolve(strict=True)
    if not target.is_dir() or source == target:
        raise ValueError('Migration requires two different home directories')
    plan = {'schema_version': SCHEMA_VERSION, 'source_home': str(source), 'target_home': str(target),
            'source_roots': manifest['source_roots'], 'target_roots': _roots(target, target_xdg, use_environment=True),
            'selected_categories': sorted(selected), 'entries': [], 'conflicts': [], 'skipped': [],
            'excluded': manifest['excluded'], 'account': manifest['account']}
    for item in manifest['files']:
        if item['category'] not in selected:
            continue
        item = dict(item)
        if item['path'] in skipped:
            plan['skipped'].append({**item, 'reason': 'user_preserved'})
            continue
        if item['review_required'] and item['path'] not in approved:
            plan['skipped'].append({**item, 'reason': 'requires_individual_review'})
            continue
        try:
            destination = destination_path(plan, item)
            if destination == source_path(plan, item):
                raise ValueError('Source and destination resolve to the same file')
            if destination.exists():
                existing, _ = _read(destination)
                item['previous_sha256'] = _digest(existing)
                if item['sha256'] == item['previous_sha256']:
                    plan['skipped'].append({**item, 'reason': 'identical'})
                    continue
                if item['path'] not in overwrite:
                    plan['conflicts'].append({**item, 'reason': 'preserving_existing_user_file'})
                    continue
            else:
                item['previous_sha256'] = None
        except (OSError, ValueError) as error:
            plan['conflicts'].append({**item, 'reason': str(error)})
            continue
        plan['entries'].append(item)
    return plan


def _write_atomic(path, data, mode=0o600):
    fd, temporary = tempfile.mkstemp(prefix='.adws-migrate-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
            os.fchmod(file.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_journal(directory, journal):
    _write_atomic(directory / 'migration.json', (json.dumps(journal, ensure_ascii=False, indent=2) + '\n').encode())


def apply_migration(plan, backup_dir):
    """Apply exactly a reviewed plan, rechecking every fingerprint before writing.

    backup_dir must not exist. Journals are written before each replacement so a
    later process can recover an interrupted copy. Existing conflicts are never
    silently promoted to entries.
    """
    if plan.get('schema_version') not in SUPPORTED_SCHEMAS:
        raise ValueError('Unsupported migration schema')
    source = Path(plan['source_home']).resolve(strict=True)
    target = Path(plan['target_home']).resolve(strict=True)
    if source == target:
        raise ValueError('Source and target homes must differ')
    prepared = []
    total_bytes = 0
    seen = set()
    target_paths = set()
    for entry in plan['entries']:
        relative = entry['path']
        category, _ = _rule(relative)
        if relative in seen:
            raise ValueError('Duplicate migration target: ' + relative)
        seen.add(relative)
        data, mode = _read(source_path(plan, entry))
        if _digest(data) != entry['sha256'] or _blocked_shell(category, data):
            raise ValueError('Source changed after review: ' + relative)
        if 'content_override' in entry:
            if category != 'defaults' or not isinstance(entry['content_override'], str):
                raise ValueError('Only reviewed default associations may use generated content')
            data = entry['content_override'].encode('utf-8')
        destination = destination_path(plan, entry)
        if destination in target_paths or destination == source_path(plan, entry):
            raise ValueError('Migration resolves to a duplicate or source target')
        target_paths.add(destination)
        old, old_mode = _read(destination) if destination.exists() else (None, None)
        if (_digest(old) if old is not None else None) != entry['previous_sha256']:
            raise ValueError('Target changed after review: ' + relative)
        total_bytes += len(data) + (len(old) if old is not None else 0)
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError('Migration batch exceeds memory limit; select fewer categories')
        prepared.append((relative, data, mode, old, old_mode))
    directory = Path(backup_dir).expanduser().absolute()
    if directory.is_symlink():
        raise ValueError('Backup directory cannot be a symlink')
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    journal = {'schema_version': SCHEMA_VERSION, 'target_home': str(target),
               'target_roots': plan.get('target_roots') or _roots(target), 'status': 'applying',
               'entries': [], 'created_directories': []}
    _save_journal(directory, journal)
    try:
        for index, (relative, data, mode, old, old_mode) in enumerate(prepared):
            destination = destination_path(plan, relative)
            # Recheck again immediately before replacing each destination.
            current = _read(destination)[0] if destination.exists() else None
            if current != old:
                raise ValueError('Target changed during migration: ' + relative)
            missing = []
            parent = destination.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir()
                journal['created_directories'].append(str(parent))
            backup_name = str(index) + '.original'
            if old is not None:
                _write_atomic(directory / backup_name, old, 0o600)
            journal['entries'].append({'path': relative, 'installed_sha256': _digest(data),
                                       'previous_sha256': _digest(old) if old is not None else None,
                                       'previous_mode': old_mode, 'backup': backup_name})
            _save_journal(directory, journal)
            _write_atomic(destination, data, mode)
        journal['status'] = 'complete'
        _save_journal(directory, journal)
    except BaseException:
        rollback(directory)
        raise
    needs_review = bool(plan.get('conflicts')) or any(
        item.get('reason') == 'requires_individual_review' for item in plan.get('skipped', []))
    return {'status': 'needs_review' if needs_review else 'complete',
            'backup': str(directory), 'copied': [p[0] for p in prepared],
            'conflicts': plan.get('conflicts', []), 'skipped': plan.get('skipped', [])}


def rollback(backup_dir):
    """Restore migration writes, preserving any subsequent user modifications."""
    directory = Path(backup_dir).expanduser().resolve(strict=True)
    journal = json.loads((directory / 'migration.json').read_text())
    if journal.get('schema_version') not in SUPPORTED_SCHEMAS:
        raise ValueError('Unsupported rollback schema')
    target = Path(journal['target_home']).resolve(strict=True)
    restored, conflicts = [], []
    for index in reversed(range(len(journal['entries']))):
        entry = journal['entries'][index]
        relative = entry['path']
        try:
            _rule(relative)
            destination = destination_path(journal, entry)
            data = _read(destination)[0] if destination.exists() else None
            digest = _digest(data) if data is not None else None
            if digest == entry['previous_sha256']:
                continue  # Already restored, or interruption happened before write.
            if digest != entry['installed_sha256']:
                raise ValueError('Changed since migration; preserving user edit')
            if entry['previous_sha256'] is None:
                destination.unlink()
            else:
                original, _ = _read(directory / (str(index) + '.original'))
                if _digest(original) != entry['previous_sha256']:
                    raise ValueError('Backup integrity check failed')
                _write_atomic(destination, original, entry['previous_mode'] & 0o777)
            restored.append(relative)
        except (OSError, ValueError) as error:
            conflicts.append({'path': relative, 'reason': str(error)})
    for relative in reversed(journal.get('created_directories', [])):
        try:
            if journal.get('schema_version') == 1:
                directory_path = _safe(target, relative)
            else:
                directory_path = Path(relative)
                roots = [Path(p) for p in journal['target_roots'].values()]
                if not directory_path.is_absolute() or not any(directory_path.is_relative_to(p) for p in roots):
                    raise ValueError('Created directory outside migration roots')
                if directory_path.is_symlink(): raise ValueError('Created directory became a symlink')
            directory_path.rmdir()
        except (OSError, ValueError):
            pass
    journal['status'] = 'rollback_conflicts' if conflicts else 'rolled_back'
    journal['rollback_conflicts'] = conflicts
    _save_journal(directory, journal)
    return {'status': journal['status'], 'restored': restored, 'conflicts': conflicts}

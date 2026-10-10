"""Track shipped templates so updates preserve edits, not obsolete defaults."""
import hashlib
from pathlib import Path
import shutil


def hashes(root):
    folder = root/'config'
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file() and not p.is_symlink()}


def preserve(root, prepared, baseline):
    old, new = root/'config', prepared/'config'
    if not old.is_dir(): return
    for source in old.rglob('*'):
        relative = source.relative_to(old)
        # Application-managed rules must always come from the new release.
        if relative.as_posix() == 'adws-windows.kdl': continue
        if source.is_symlink() or not source.is_file(): continue
        target = new/relative
        previous = baseline.get(relative.as_posix())
        modified = previous is not None and hashlib.sha256(source.read_bytes()).hexdigest() != previous
        # Legacy installs have no baseline. Keep conflicting files in the full
        # update backup rather than guessing that every old default was edited.
        if modified or (previous is None and not target.exists()):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    # Migrate preserved custom Waybar fonts too, without replacing their theme.
    from adws_fonts import with_symbol_fallbacks
    for target in (new/'waybar').glob('*.css'):
        text = target.read_text(encoding='utf-8')
        migrated = with_symbol_fallbacks(text)
        if migrated != text:
            target.write_text(migrated, encoding='utf-8')


def live_font_changes(root):
    """Plan changes to user Waybar styles; never overwrite swapped project files."""
    import json
    import os
    from adws_fonts import with_symbol_fallbacks
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
    paths = list((config/'waybar').rglob('*.css'))
    profile = config/'adws/waybar-top.json'
    if profile.is_file():
        data = json.loads(profile.read_text(encoding='utf-8'))
        if isinstance(data, dict) and isinstance(data.get('style'), str):
            paths.append(Path(os.path.expandvars(data['style'])).expanduser())
    changes = {}
    for original in paths:
        path = original.resolve()
        if path.is_relative_to(root.resolve()) or path in changes or not path.is_file():
            continue
        if path.stat().st_size > 2*1024*1024:
            continue
        before = path.read_bytes()
        after = with_symbol_fallbacks(before.decode('utf-8')).encode('utf-8')
        if after != before:
            changes[path] = (before, after, path.stat().st_mode & 0o777)
    return changes


def apply_font_changes(changes, backup, on_publish=None):
    """Save durable backups before replacing the complete set atomically."""
    import json
    from adws_atomic import replace_files
    for path, (before, after, mode) in changes.items():
        if path.read_bytes() != before:
            raise RuntimeError('Waybar style changed while preparing font migration: '+str(path))
    folder = backup/'waybar-font-styles'
    folder.mkdir(exist_ok=True)
    manifest = []
    for index, (path, (before, after, mode)) in enumerate(changes.items()):
        snapshot = folder/(str(index)+'.css')
        snapshot.write_bytes(before); snapshot.chmod(mode)
        manifest.append({'path':str(path), 'backup':snapshot.name, 'mode':mode})
    (folder/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if on_publish:
        on_publish()
    replace_files({path:after for path, (before, after, mode) in changes.items()})


def restore_font_changes(changes):
    from adws_atomic import replace_files
    replace_files({path:before for path, (before, after, mode) in changes.items()})

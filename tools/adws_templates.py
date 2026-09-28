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

"""Durable file replacement with rollback for a small configuration bundle."""
import os
from pathlib import Path
import tempfile


def stage(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.adws-write-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode if mode is not None else path.stat().st_mode & 0o777 if path.exists() else 0o644)
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def replace_files(files):
    # Follow symlinks without replacing them. Stage every file before publishing
    # any: readers see complete files, and a failed replacement restores the set.
    prepared, previous, replaced = {}, {}, []
    try:
        for original, content in files.items():
            path = Path(original).resolve()
            if path in prepared:
                raise ValueError('Configuration targets resolve to the same file')
            previous[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
            prepared[path] = stage(path, content)
        for path, temporary in prepared.items():
            try:
                os.replace(temporary, path)
            finally:
                # A signal may arrive after rename succeeds but before Python
                # records it. A consumed staged file still needs rollback.
                if not temporary.exists(): replaced.append(path)
    except BaseException as error:
        failures = []
        for path in reversed(replaced):
            try:
                old = previous[path]
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    temporary = stage(path, old[0], old[1])
                    try: os.replace(temporary, path)
                    finally: temporary.unlink(missing_ok=True)
            except OSError as exc:
                failures.append(str(exc))
        if failures:
            raise OSError('Configuration rollback failed: ' + '; '.join(failures)) from error
        raise
    finally:
        for temporary in prepared.values(): temporary.unlink(missing_ok=True)

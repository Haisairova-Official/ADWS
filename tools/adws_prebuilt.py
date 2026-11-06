"""Verify bundled native components before installing them.

The installed system loader is used only with --list (not ldd -r or dlopen):
https://man7.org/linux/man-pages/man8/ld.so.8.html
https://man7.org/linux/man-pages/man1/ldd.1.html
ELF symbol tables are read as data, so unresolved non-versioned GTK APIs are
also detected without invoking application code, constructors or IFUNCs.
"""
from adws_i18n import tr as _tr
import hashlib
import json
import mmap
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import tempfile

NAMES = ('libniri_taskbar.so', 'libadws_panel.so', 'libwaybar-space.so', 'adws-plugin-runner', 'adws-start-menu')
SYSTEM_LOADERS = ('/usr/lib/ld-linux-x86-64.so.2', '/lib64/ld-linux-x86-64.so.2', '/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2')
MAX_ARTIFACT = 512 * 1024 * 1024
CHECK_ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'LANG': 'C'}


class PrebuiltIntegrityError(RuntimeError):
    """Damaged/incomplete artifacts must never become a source-build bypass."""


class ElfUnsupported(RuntimeError):
    """A valid ELF cannot be verified on the supported target ABI."""


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_artifacts(root):
    """Return the verified manifest, or None only for a source-only tree."""
    folder = Path(root) / 'prebuilt'
    if not folder.exists() and not folder.is_symlink():
        return None
    manifest = folder / 'manifest.json'
    try:
        if folder.is_symlink() or manifest.is_symlink() or not manifest.is_file():
            raise ValueError('missing or symlinked manifest')
        if manifest.stat().st_size > 1024 * 1024:
            raise ValueError('oversized manifest')
        data = json.loads(manifest.read_text())
        hashes = data['sha256']
        if not isinstance(hashes, dict):
            raise ValueError('invalid checksum inventory')
        for name in NAMES:
            path = folder / name
            expected = hashes.get(name)
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ARTIFACT:
                raise ValueError(name + ': missing, empty, linked or oversized component')
            if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected) or _digest(path) != expected:
                raise ValueError(name + ': SHA256 mismatch')
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PrebuiltIntegrityError(_tr('预构建文件校验失败，请重新下载安装包：') + str(exc)) from exc


def elf_metadata(path):
    """Parse bounded ELF64 tables without executing the file or requiring binutils."""
    path = Path(path)
    try:
        size = path.stat().st_size
        if not 64 <= size <= MAX_ARTIFACT:
            raise ValueError('invalid ELF length')
        with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            def block(offset, length):
                if offset < 0 or length < 0 or offset + length > size:
                    raise ValueError('ELF table outside file')
                return data[offset:offset + length]
            def unpack(fmt, offset):
                return struct.unpack(fmt, block(offset, struct.calcsize(fmt)))
            if block(0, 4) != b'\x7fELF':
                raise ValueError('not an ELF artifact')
            if data[4] != 2 or data[5] != 1:
                raise ElfUnsupported('Requires ELF64 little-endian x86_64')
            if data[6] != 1:
                raise ValueError('invalid ELF identification version')
            header = unpack('<HHIQQQIHHHHHH', 16)
            kind, machine, version, _, phoff, shoff, _, ehsize, phsize, phnum, shsize, shnum, _ = header
            if machine != 62:
                raise ElfUnsupported('ELF machine does not match x86_64: ' + str(machine))
            if kind not in (2, 3) or version != 1 or ehsize != 64:
                raise ValueError('invalid executable/shared ELF header')
            if phnum > 4096 or (phnum and phsize != 56):
                raise ValueError('invalid ELF program headers')
            interpreter = None
            for i in range(phnum):
                typ, _, offset, _, _, length, _, _ = unpack('<IIQQQQQQ', phoff + i * phsize)
                if typ == 3:  # PT_INTERP
                    raw = block(offset, length)
                    if not raw.endswith(b'\0') or b'\0' in raw[:-1] or length > 4096:
                        raise ValueError('invalid ELF interpreter')
                    interpreter = raw[:-1].decode('utf-8')
            if not shoff:
                raise ElfUnsupported('ELF lacks section tables required for non-executing ABI verification')
            if shsize != 64:
                raise ValueError('invalid section entry size')
            first = unpack('<IIQQQQIIQQ', shoff)
            if shnum == 0:
                shnum = first[5]
            if not 0 < shnum <= 65536:
                raise ValueError('invalid section count')
            sections = [unpack('<IIQQQQIIQQ', shoff + i * shsize) for i in range(shnum)]
            def section_bytes(section):
                return block(section[4], section[5])
            def strings(section):
                if section[6] >= len(sections) or sections[section[6]][1] != 3:
                    raise ValueError('invalid ELF string table link')
                table = section_bytes(sections[section[6]])
                def read(index):
                    if index >= len(table):
                        raise ValueError('invalid ELF string offset')
                    end = table.find(b'\0', index)
                    if end < 0:
                        raise ValueError('unterminated ELF string')
                    return table[index:end].decode('utf-8')
                return read
            versions = {}
            for section in sections:
                typ = section[1]
                if typ not in (0x6ffffffe, 0x6ffffffd):
                    continue
                text = strings(section)
                raw = section_bytes(section)
                offset = 0
                visited = set()
                while offset < len(raw):
                    if offset in visited:
                        raise ValueError('cyclic ELF symbol versions')
                    visited.add(offset)
                    if typ == 0x6ffffffe:  # Elf64_Verneed, then Vernaux
                        _, count, _, aux, following = struct.unpack_from('<HHIII', raw, offset)
                        pos = offset + aux
                        for _ in range(count):
                            _, _, index, name, next_aux = struct.unpack_from('<IHHII', raw, pos)
                            versions[index & 0x7fff] = text(name)
                            if not next_aux:
                                break
                            pos += next_aux
                    else:  # Elf64_Verdef, first Verdaux is the version name
                        _, _, index, _, _, aux, following = struct.unpack_from('<HHHHIII', raw, offset)
                        name, _ = struct.unpack_from('<II', raw, offset + aux)
                        versions[index & 0x7fff] = text(name)
                    if not following:
                        break
                    offset += following
            exported, required, needed, tags, search_paths = set(), set(), [], set(), []
            dynsyms = [s for s in sections if s[1] == 11]
            if not dynsyms:
                raise ElfUnsupported('ELF has no dynamic symbol table')
            for section in sections:
                if section[1] != 6:  # SHT_DYNAMIC
                    continue
                if section[9] != 16 or section[5] % 16:
                    raise ValueError('invalid dynamic section')
                text = strings(section)
                for offset in range(section[4], section[4] + section[5], 16):
                    tag, value = unpack('<qQ', offset)
                    tags.add(tag)
                    if tag == 1:
                        needed.append(text(value))
                    elif tag in (15, 29):
                        search_paths.extend(text(value).split(':'))
            # Audit/filter objects may load executable callbacks during inspection.
            # They are not part of the ADWS release contract.
            if tags & {0x6ffffefb, 0x6ffffefc, 0x7fffffff, 0x7ffffffd}:
                raise ElfUnsupported('ELF audit/filter callbacks are not supported for safe compatibility inspection')
            for section in dynsyms:
                if section[9] != 24 or section[5] % 24:
                    raise ValueError('invalid dynamic symbol table')
                text = strings(section)
                section_index = sections.index(section)
                ver = next((s for s in sections if s[1] == 0x6fffffff and s[6] == section_index), None)
                count = section[5] // 24
                version_table = section_bytes(ver) if ver else b''
                if ver and len(version_table) < count * 2:
                    raise ValueError('truncated symbol-version table')
                for i in range(count):
                    name, info, other, defined, _, _ = unpack('<IBBHQQ', section[4] + i * 24)
                    binding = info >> 4
                    if not name or binding not in (1, 2, 10):
                        continue
                    name = text(name)
                    raw_version = struct.unpack_from('<H', version_table, i * 2)[0] if ver else 0
                    version_index = raw_version & 0x7fff
                    version_name = versions.get(version_index) if version_index > 1 else None
                    if version_index > 1 and not version_name:
                        raise ValueError('symbol references an undefined version')
                    if defined == 0:
                        if binding != 2:  # unresolved weak imports are permitted
                            required.add((name, version_name))
                    elif other & 3 in (0, 3):  # DEFAULT/PROTECTED visibility
                        exported.add((name, version_name))
                        if not raw_version & 0x8000:
                            exported.add((name, None))
            return {'interpreter': interpreter, 'needed': needed, 'required': required, 'exported': exported, 'search_paths': search_paths}
    except ElfUnsupported:
        raise
    except (OSError, ValueError, UnicodeError, struct.error) as exc:
        raise PrebuiltIntegrityError('Invalid ELF ' + str(path) + ': ' + str(exc)) from exc


def _system_loader():
    for name in SYSTEM_LOADERS:
        path = Path(name)
        if path.is_file():
            return str(path.resolve())
    return None


def _dependency_paths(output):
    paths = []
    for line in output.splitlines():
        # Retain spaces in a path; remove only the loader's trailing address.
        value = line.split('=>', 1)[-1].strip()
        value = re.sub(r'\s+\(0x[0-9a-fA-F]+\)\s*$', '', value)
        if value.startswith('/'):
            paths.append(Path(value))
    return list(dict.fromkeys(paths))


def inspect_compatibility(root, *, runner=subprocess.run, loader=None):
    """Return a serializable runtime ABI report after dependencies are installed.

    Integrity errors raise and cannot be treated as permission to build source.
    Dynamic loader --list resolves libraries and checks required symbol versions;
    our static symbol check also catches newer unversioned GTK/library APIs.
    """
    root = Path(root)
    manifest = verify_artifacts(root)
    if manifest is None:
        return {'status': 'source-only', 'compatible': False, 'components': [], 'errors': []}
    metadata = {}
    errors = []
    for name in NAMES:
        try:
            metadata[name] = elf_metadata(root / 'prebuilt' / name)
        except ElfUnsupported as exc:
            errors.append({'component': name, 'kind': 'unsupported-elf', 'detail': str(exc)})
    try:
        host_os = platform.freedesktop_os_release().get('ID')
    except OSError:
        host_os = None
    if host_os != 'arch' or platform.machine() != 'x86_64' or manifest.get('os', 'arch') != 'arch' or manifest.get('arch', 'x86_64') != 'x86_64':
        errors.append({'component': None, 'kind': 'platform', 'detail': 'Prebuilt components require Arch Linux x86_64'})
    if errors:
        return {'status': 'incompatible', 'compatible': False, 'components': [], 'errors': errors}
    loader = loader or _system_loader()
    if not loader:
        return {'status': 'unverified', 'compatible': False, 'components': [], 'errors': [{'component': None, 'kind': 'loader-missing', 'detail': 'System glibc loader not found'}]}
    # An injectable path supports isolated fixture tests. Production never chooses
    # a loader from an artifact's interpreter or from PATH.
    if runner is subprocess.run and Path(loader).resolve() not in {Path(p).resolve() for p in SYSTEM_LOADERS if Path(p).is_file()}:
        raise ValueError('Only the installed system loader can inspect release binaries')
    cache = {}
    components = []
    for name in NAMES:
        artifact = root / 'prebuilt' / name
        info = metadata[name]
        if info['interpreter'] and (info['interpreter'] not in SYSTEM_LOADERS or not Path(info['interpreter']).is_file()):
            errors.append({'component': name, 'kind': 'interpreter', 'detail': 'Unsupported or missing ELF interpreter: ' + info['interpreter']})
            continue
        if name in ('adws-start-menu', 'adws-plugin-runner') and not info['interpreter']:
            errors.append({'component': name, 'kind': 'interpreter', 'detail': 'Dynamic executable has no ELF interpreter'})
            continue
        if any('/' in item or '$' in item for item in info['needed']) or any(item not in ('/usr/lib', '/usr/lib64', '/lib', '/lib64', '/lib/x86_64-linux-gnu', '/usr/lib/x86_64-linux-gnu') for item in info['search_paths']):
            errors.append({'component': name, 'kind': 'relocation-path', 'detail': 'Custom/relative ELF dependency paths cannot be verified after installation to another directory'})
            continue
        try:
            reply = runner([loader, '--list', str(artifact.resolve())], capture_output=True, text=True, timeout=20, env=dict(CHECK_ENV))
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append({'component': name, 'kind': 'loader-check', 'detail': str(exc)})
            continue
        details = (reply.stderr or '').strip()
        if reply.returncode != 0 or re.search(r'not found|undefined symbol|error while loading', details + '\n' + reply.stdout, re.I):
            errors.append({'component': name, 'kind': 'dependency-abi', 'detail': (details or reply.stdout.strip() or 'Loader check failed')[:8000]})
            continue
        dependencies = _dependency_paths(reply.stdout)
        if info['needed'] and not dependencies:
            errors.append({'component': name, 'kind': 'unverified', 'detail': 'Loader returned no dependency inventory'})
            continue
        exported = set(info['exported'])
        dependency_error = False
        for dependency in [*dependencies, Path(loader)]:
            try:
                key = dependency.resolve()
                if key not in cache:
                    cache[key] = elf_metadata(key)
                exported.update(cache[key]['exported'])
            except (PrebuiltIntegrityError, ElfUnsupported) as exc:
                # These are installed system libraries, not package corruption.
                errors.append({'component': name, 'kind': 'system-abi-unverified', 'detail': str(exc)})
                dependency_error = True
                break
        if dependency_error:
            continue
        missing = sorted(info['required'] - exported, key=lambda symbol: (symbol[0], symbol[1] or ''))
        if missing:
            errors.append({'component': name, 'kind': 'missing-symbols', 'detail': ', '.join(n + ('@' + v if v else '') for n, v in missing[:80])})
            continue
        components.append({'component': name, 'status': 'compatible', 'dependencies': [str(p) for p in dependencies]})
    # Catch a changed artifact before any caller could install it after the probe.
    if verify_artifacts(root) != manifest:
        raise PrebuiltIntegrityError('Prebuilt manifest changed during ABI verification')
    return {'status': 'compatible' if not errors else 'incompatible', 'compatible': not errors, 'components': components, 'errors': errors,
            'method': 'system-loader-list-and-static-elf-symbols'}


def _fallback_approved():
    if os.environ.get('ADWS_INSTALL_MANAGED') == '1':
        from adws_install_workflow import approved_plan
        proposal = approved_plan()
        return bool(proposal and proposal.get('build_fallback') is True)
    return False


def install(root, destination, confirm, atomic_install, *, compatibility_checker=None):
    root, destination = Path(root), Path(destination)
    manifest = verify_artifacts(root)
    if manifest is None:
        return False
    report = (compatibility_checker or inspect_compatibility)(root)
    if not report['compatible']:
        detail = '\n'.join((row.get('component') or 'system') + ': ' + row['detail'] for row in report['errors'])
        if _fallback_approved():
            print(_tr('预编译组件与当前运行库不兼容，按已确认计划转为源码构建：\n') + detail)
            return False
        raise RuntimeError(_tr('预编译兼容性检查未通过，尚未安装任何组件。请使用匹配的安装包，或明确允许源码构建后重试：\n') + detail)
    if not confirm(_tr('是否快速安装预构建组件？无需 Rust/Cargo 或 C 编译器。')):
        raise RuntimeError(_tr('已取消预构建组件安装。'))
    # A confirmation dialog can remain open while files change. Recheck before
    # entering the first write, not only before the potentially lengthy probe.
    if verify_artifacts(root) != manifest:
        raise PrebuiltIntegrityError('Prebuilt manifest changed after compatibility review')
    # Freeze a verified copy of the whole set before the first destination write.
    # The source tree changing halfway through installation cannot mix two builds.
    with tempfile.TemporaryDirectory(prefix='adws-prebuilt-') as directory:
        staged = Path(directory)
        for name in NAMES:
            source = root / 'prebuilt' / name
            if source.is_symlink():
                raise PrebuiltIntegrityError('Prebuilt component became a symlink: ' + name)
            shutil.copy2(source, staged / name)
            if _digest(staged / name) != manifest['sha256'][name]:
                raise PrebuiltIntegrityError('Prebuilt component changed while staging: ' + name)
        for name in NAMES:
            if name in ('adws-plugin-runner', 'adws-start-menu'):
                atomic_install(staged / name, root / 'libexec' / name, mode=0o755)
            else:
                atomic_install(staged / name, destination / name)
    print(_tr('预构建组件兼容性检查通过并安装完成，已跳过源码编译。'))
    return True

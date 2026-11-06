"""Read-only Arch full-upgrade preview; execution always belongs to pacman.

The current system sync databases are never refreshed here. Fresh databases go
into a private directory, with only the installed package database linked in.
No downloaded archive is extracted or executed. The preview is advisory: the
real transaction must show its refreshed package list and ask for confirmation.

https://man.archlinux.org/man/pacman.8.en (print-format, --print, --sysupgrade)
https://man.archlinux.org/man/pacman.conf.5.en (SigLevel, Usage, Server)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 192 * 1024 * 1024
_PACKAGE = re.compile(r'[A-Za-z0-9@._+\-]+(?:/[A-Za-z0-9@._+\-]+)?\Z')
_REPO = re.compile(r'[A-Za-z0-9@._+\-]+\Z')


def _packages(packages):
    result = list(dict.fromkeys(packages))
    if len(result) > 1024 or any(not isinstance(p, str) or not _PACKAGE.fullmatch(p)
                               or any(part in ('.', '..') or part.startswith('-') for part in p.split('/')) for p in result):
        raise ValueError('Invalid Arch package targets')
    return result


def execution_command(packages, *, pacman_conf='/etc/pacman.conf'):
    """Never add --noconfirm, -Sy alone, or any user-writable database path."""
    return ['pacman', '--config', str(pacman_conf), '-Syu', '--needed', '--', *_packages(packages)]


def _redact(message):
    # Mirror paths, query strings and URL credentials may contain private tokens.
    text = re.sub(r'(?:https?|ftp|file)://[^\s\x00-\x20]+', '[repository URL redacted]', str(message))
    return ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)[:8192]


def _query_config(path, run, timeout):
    result = run(['pacman-conf', '--config', str(path)], capture_output=True, text=True,
                 timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise ValueError('Cannot read effective pacman configuration: ' + _redact(result.stderr))
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError('Effective pacman configuration exceeds preview limit')
    sections = {}; section = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            if section in sections: raise ValueError('Duplicate effective repository section')
            sections[section] = {}
        elif section is not None:
            name, _, value = line.partition('=')
            sections[section].setdefault(name.strip(), []).append(value.strip())
        else:
            raise ValueError('Unrecognized effective pacman configuration')
    return sections, hashlib.sha256(result.stdout.encode()).hexdigest()


def source_fingerprint(pacman_conf='/etc/pacman.conf', *, runner=None, timeout=20):
    """Hash expanded config, including all Include files, without recording URLs."""
    return _query_config(pacman_conf, runner or subprocess.run, timeout)[1]


def verify_sources(proposal, *, runner=None):
    expected = proposal.get('source_fingerprint')
    if not expected or source_fingerprint(proposal['pacman_conf'], runner=runner) != expected:
        raise ValueError('Pacman sources or policies changed; review a new installation plan')
    return True


def _database_policy(values):
    policy = 'Optional'
    for token in ' '.join(values).split():
        if token in ('Required', 'Optional', 'Never'): policy = token
        elif token in ('DatabaseRequired', 'DatabaseOptional', 'DatabaseNever'): policy = token[8:]
    return policy


def _database_url(server, repo, suffix):
    parts = urllib.parse.urlsplit(server)
    if (parts.scheme not in ('https', 'http', 'file') or parts.username or parts.password or parts.fragment
            or (parts.scheme != 'file' and not parts.hostname) or (parts.scheme == 'file' and parts.netloc not in ('', 'localhost'))):
        raise ValueError('Repository transport requires native pacman review')
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') + '/' + repo + suffix, parts.query, ''))


class _NoDowngrade(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(request.full_url); new = urllib.parse.urlsplit(newurl)
        if new.scheme not in ('https', 'http') or new.username or new.password or (old.scheme == 'https' and new.scheme != 'https'):
            raise ValueError('Unsafe repository redirect')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _fetch(url, target, *, opener, deadline, maximum):
    remaining = deadline - time.monotonic()
    if remaining <= 0: raise TimeoutError('Package preview timed out')
    request = urllib.request.Request(url, headers={'User-Agent': 'ADWS-package-review', 'Accept-Encoding': 'identity'})
    count = 0
    with opener(request, timeout=min(15, remaining)) as response, target.open('wb') as stream:
        length = response.headers.get('Content-Length')
        if length is not None and (int(length) < 0 or int(length) > maximum):
            raise ValueError('Repository database exceeds preview limit')
        if response.headers.get('Content-Encoding', 'identity') not in ('identity', ''):
            raise ValueError('Unexpected encoded repository response')
        while data := response.read(64 * 1024):
            count += len(data)
            if count > maximum: raise ValueError('Repository database exceeds preview limit')
            if time.monotonic() >= deadline: raise TimeoutError('Package preview timed out')
            stream.write(data)
        if not count or (length is not None and count != int(length)):
            raise ValueError('Incomplete repository database response')
    return count


def review(packages, *, pacman_conf='/etc/pacman.conf', timeout=120,
           max_database_bytes=MAX_DATABASE_BYTES, runner=None, opener=None):
    """Preview all system upgrades plus requested packages without root access.

    ``reviewed`` means pacman resolved the downloaded databases under the current
    configuration. It is not installation authorization or file-conflict proof.
    Signed/custom transports we cannot verify read-only return
    ``requires_interactive_review``; no signature policy is weakened.
    ``conflicts`` contains only actual preview issues, not a complete proof of
    transaction compatibility. Sensitive mirror URLs are never included.
    """
    packages = _packages(packages)
    if not 1 <= timeout <= 600 or not 1 <= max_database_bytes <= MAX_TOTAL_BYTES:
        raise ValueError('Invalid package preview limits')
    run = runner or subprocess.run
    open_url = opener or urllib.request.build_opener(_NoDowngrade()).open
    deadline = time.monotonic() + timeout
    report = {'schema_version': 1, 'status': 'requires_interactive_review', 'packages': packages,
              'pacman_conf': str(pacman_conf), 'source_fingerprint': None,
              'resolved_packages': [], 'total_download_bytes': 0, 'repositories': [], 'conflicts': [],
              'download_estimate': 'package archive sizes before reuse of any existing system cache',
              'execution_requires_confirmation': True, 'system_upgrade': True,
              'conflict_check': 'dependency preview only; pacman must check current transaction and file conflicts',
              'policy': 'Preview never changes system databases. Execution refreshes them and must show its new package list for approval.'}
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0: raise TimeoutError('Package preview timed out')
        return value
    try:
        config, report['source_fingerprint'] = _query_config(pacman_conf, run, min(20, remaining()))
        options = config.pop('options', {})
        if not config or len(config) > 32 or any(not _REPO.fullmatch(name) or name in ('.', '..') for name in config):
            raise ValueError('Repository inventory cannot be safely previewed')
        if options.get('RootDir', ['/']) != ['/'] or options.get('XferCommand'):
            raise ValueError('Custom root or transfer command requires native pacman review')
        local = Path(options.get('DBPath', ['/var/lib/pacman/'])[0]) / 'local'
        if not local.is_absolute() or not local.is_dir(): raise ValueError('Installed package database is unavailable')
        with tempfile.TemporaryDirectory(prefix='adws-pacman-review-') as directory:
            temporary = Path(directory); (temporary/'sync').mkdir(); (temporary/'cache').mkdir()
            (temporary/'local').symlink_to(local, target_is_directory=True)
            total = 0
            for name, entry in config.items():
                signature = options.get('SigLevel', []) + entry.get('SigLevel', [])
                policy = _database_policy(signature)
                row = {'name': name, 'signature_policy': signature, 'database_signature': 'not-reviewed'}
                report['repositories'].append(row)
                if policy == 'Required':
                    raise ValueError('Repository ' + name + ' requires signed database verification by native pacman')
                servers = entry.get('Server', [])
                if not servers: raise ValueError('Repository ' + name + ' has no supported server')
                downloaded = False
                for server in servers[:3]:
                    database = temporary/'sync'/(name+'.db'); signature_file = database.with_suffix('.db.sig')
                    database.unlink(missing_ok=True); signature_file.unlink(missing_ok=True)
                    try:
                        url = _database_url(server, name, '.db')
                        size = _fetch(url, database, opener=open_url, deadline=deadline,
                                      maximum=min(max_database_bytes, MAX_TOTAL_BYTES-total))
                        total += size
                        if policy != 'Never':
                            try:
                                _fetch(_database_url(server, name, '.db.sig'), signature_file, opener=open_url,
                                       deadline=deadline, maximum=1024*1024)
                            except urllib.error.HTTPError as error:
                                error.close()
                                if error.code not in (404, 410): raise
                            except urllib.error.URLError as error:
                                if not (urllib.parse.urlsplit(url).scheme == 'file' and isinstance(error.reason, FileNotFoundError)): raise
                            if signature_file.exists() and signature_file.stat().st_size:
                                raise ValueError('Signed repository database requires native pacman verification')
                        row.update(database_signature='disabled-by-existing-policy' if policy == 'Never' else 'unsigned-allowed-by-existing-policy',
                                   database_bytes=size, database_sha256=hashlib.sha256(database.read_bytes()).hexdigest())
                        downloaded = True; break
                    except (urllib.error.URLError, OSError) as error:
                        if isinstance(error, urllib.error.HTTPError): error.close()
                        if time.monotonic() >= deadline: raise TimeoutError('Package preview timed out') from error
                        # No URLs or exception bodies are persisted, including credentials.
                        continue
                if not downloaded: raise ValueError('Repository '+name+' could not be safely downloaded; use native pacman review')
            command = ['pacman', '--config', str(pacman_conf), '-Su', '--needed', '--print',
                       '--print-format', 'ADWS_PACKAGE\t%n\t%v\t%s\t%r',
                       '--dbpath', directory, '--logfile', str(temporary/'pacman.log'),
                       '--cachedir', str(temporary/'cache'), '--noconfirm', '--', *packages]
            result = run(command, capture_output=True, text=True, timeout=remaining(),
                         env={**os.environ, 'LC_ALL': 'C'})
            if result.returncode:
                raise ValueError('Pacman could not resolve the preview: '+_redact(result.stderr))
            if len(result.stdout) > 8*1024*1024: raise ValueError('Package preview output exceeds limit')
            resolved = []
            for line in result.stdout.splitlines():
                if not line.startswith('ADWS_PACKAGE\t'): continue
                fields = line.split('\t')
                if len(fields) != 5 or not _PACKAGE.fullmatch(fields[1]) or not fields[3].isdigit() or fields[4] not in config:
                    raise ValueError('Unrecognized package preview record')
                resolved.append({'name': fields[1], 'version': fields[2], 'download_bytes': int(fields[3]), 'repository': fields[4]})
            if result.stdout.strip() and not resolved and 'there is nothing to do' not in result.stdout:
                raise ValueError('Pacman returned no recognizable package preview')
            if _query_config(pacman_conf, run, min(20, remaining()))[1] != report['source_fingerprint']:
                raise ValueError('Pacman source configuration changed during preview')
            report.update(status='reviewed', resolved_packages=resolved,
                          total_download_bytes=sum(item['download_bytes'] for item in resolved),
                          diagnostics=_redact(result.stderr))
    except (ValueError, OSError, TimeoutError, subprocess.SubprocessError) as error:
        report['conflicts'].append({'kind': 'preview-requires-native-review', 'message': _redact(error)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/pacman.conf')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('packages', nargs='*')
    args = parser.parse_args()
    result = review(args.packages, pacman_conf=args.config, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'reviewed' else 2


if __name__ == '__main__':
    raise SystemExit(main())

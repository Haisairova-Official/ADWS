"""User-facing personal-environment review model for the unified installer.

All choice collection is done before the installation's approval. File imports
remain reversible; the optional account nickname change is a separate explicit
action and is never inferred from old caches or old account UIDs.
"""
import configparser
import difflib
import io
import json
import os
from pathlib import Path
import pwd

from adws_install_migration import (
    CATEGORIES, SCHEMA_VERSION, _read, destination_path, inventory,
    plan_migration, source_path,
)

DECISIONS = ('import', 'replace', 'keep')
MAX_PREVIEW_BYTES = 48 * 1024


def nickname_action(value=None, current=None):
    if current is None:
        account = pwd.getpwuid(os.getuid())
        current = {'uid': os.getuid(), 'name': account.pw_gecos.split(',')[0]}
    uid = current.get('uid')
    if type(uid) is not int or uid != os.getuid():
        raise ValueError('Nickname migration may only target the current user')
    action = {'type': 'nickname', 'uid': uid, 'before': current.get('name', ''),
              'value': current.get('name', ''), 'policy': 'preserve',
              'requires_authorization': False}
    if value is not None:
        if not isinstance(value, str) or not value.strip() or len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Nickname must be 1–128 printable characters')
        action.update(value=value.strip(), policy='set' if value.strip() != action['before'] else 'preserve',
                      requires_authorization=value.strip() != action['before'])
    return action


def _account_backend():
    from adws_native_accounts import properties, bus_call, SERVICE, USER
    class AccountBackend:
        def read(self, uid):
            data = properties(SERVICE, f'/org/freedesktop/Accounts/User{uid}', USER)
            if data.get('Uid') != uid: raise ValueError('Account identity changed')
            return data.get('RealName', '')
        def write(self, uid, name):
            bus_call(SERVICE, f'/org/freedesktop/Accounts/User{uid}', USER,
                     'SetRealName', '(s)', (name,), timeout=60000)
    return AccountBackend()


def rollback_nickname(change, backend=None):
    """Restore an applied optional nickname change unless the user edited it."""
    if change.get('status') != 'changed': return {'status': 'unchanged'}
    if type(change.get('uid')) is not int or change['uid'] != os.getuid():
        raise ValueError('Account rollback may only target the current user')
    previous = change.get('previous')
    if not isinstance(previous, str) or len(previous) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in previous):
        raise ValueError('Invalid previous nickname')
    if backend is None: backend = _account_backend()
    actual = backend.read(change['uid'])
    if actual == previous: return {'status': 'unchanged'}
    if actual != change.get('value'): return {'status': 'conflict', 'reason': 'Nickname changed after installation'}
    backend.write(change['uid'], previous)
    if backend.read(change['uid']) != previous: raise RuntimeError('Nickname rollback did not take effect')
    return {'status': 'restored'}


def apply_nickname(action, backend=None):
    """Execute an explicitly selected account action; never call from file copy.

    backend supports read(uid) -> name and write(uid, name); tests use a fake.
    Production goes through existing AccountsService authorization, retaining
    the current username, UID, account type and all other account properties.
    """
    if action.get('policy') == 'preserve': return {'status': 'preserved'}
    if action.get('policy') != 'set' or action.get('requires_authorization') is not True:
        raise ValueError('Nickname change was not selected')
    validated = nickname_action(action.get('value'), {'uid': action.get('uid'), 'name': action.get('before')})
    if backend is None: backend = _account_backend()
    previous = backend.read(validated['uid'])
    if previous == validated['value']: return {'status': 'unchanged'}
    if previous != validated['before']: raise ValueError('Account nickname changed after review')
    backend.write(validated['uid'], validated['value'])
    if backend.read(validated['uid']) != validated['value']:
        raise RuntimeError('AccountsService did not apply the selected nickname')
    return {'status': 'changed', 'uid': validated['uid'], 'previous': previous, 'value': validated['value']}


def _defaults(relative, data, installed_ids):
    """Retain only desktop IDs verified runnable on the destination machine."""
    if installed_ids is None:
        raise ValueError('Default associations require the installed target application list')
    allowed = set(installed_ids)
    if relative.endswith('default-terminal.json'):
        value = json.loads(data)
        if not isinstance(value, dict) or value.get('desktop_id') not in allowed:
            raise ValueError('The imported default terminal is not installed on the target')
        return json.dumps({'desktop_id': value['desktop_id']}, ensure_ascii=False, indent=2) + '\n', []
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(data.decode('utf-8'))
    result = configparser.ConfigParser(interpolation=None)
    result.optionxform = str
    removed = []
    kept = 0
    for section in parser.sections():
        if section not in ('Default Applications', 'Added Associations', 'Removed Associations'):
            raise ValueError('Unexpected MIME association section: ' + section)
        result.add_section(section)
        for mime, text in parser.items(section):
            ids = list(dict.fromkeys(x.strip() for x in text.split(';') if x.strip()))
            chosen = [x for x in ids if x in allowed and '/' not in x and '\\' not in x and x.endswith('.desktop')]
            removed.extend({'mime': mime, 'desktop_id': x, 'reason': 'not_installed_on_target'} for x in ids if x not in chosen)
            if chosen:
                result.set(section, mime, ';'.join(chosen) + ';')
                kept += len(chosen)
    if not kept: raise ValueError('No installed target applications remain in the imported associations')
    text = io.StringIO(); result.write(text)
    return text.getvalue(), removed


def review(source_home, target_home, categories=None, *, decisions=None,
           installed_desktop_ids=None, target_xdg=None, source_xdg=None,
           nickname=None, current_identity=None):
    """Build the complete reviewed file plan; decisions use logical inventory paths.

    import approves a new file; replace explicitly approves overwriting a
    differing file; keep deliberately preserves the target and resolves that
    review row. Unanswered review rows/conflicts stay in needs_review.
    """
    categories = list(categories if categories is not None else CATEGORIES)
    decisions = dict(decisions or {})
    manifest = inventory(source_home, source_xdg)
    known = {f['path']: f for f in manifest['files'] if f['category'] in categories}
    for relative, decision in decisions.items():
        if relative not in known: raise ValueError('Decision does not refer to an available selected file: ' + relative)
        if decision not in DECISIONS: raise ValueError('Unknown per-file migration decision: ' + str(decision))
    plan = plan_migration(source_home, target_home, categories,
                          approved_paths=[p for p,d in decisions.items() if d in ('import', 'replace')],
                          overwrite_paths=[p for p,d in decisions.items() if d == 'replace'],
                          skipped_paths=[p for p,d in decisions.items() if d == 'keep'],
                          target_xdg=target_xdg, source_xdg=source_xdg)
    plan['decisions'] = decisions
    plan['filtered_associations'] = []
    remaining = []
    for entry in plan['entries']:
        if entry['category'] == 'defaults':
            try:
                content, removed = _defaults(entry['path'], _read(source_path(plan, entry))[0], installed_desktop_ids)
                entry['content_override'] = content
                plan['filtered_associations'].extend(removed)
            except (ValueError, UnicodeError, configparser.Error) as error:
                plan['conflicts'].append({**entry, 'reason': str(error)})
                continue
        remaining.append(entry)
    plan['entries'] = remaining
    plan['account_action'] = nickname_action(nickname if 'nickname' in categories else None, current_identity)
    plan['needs_review'] = plan['conflicts'] + [r for r in plan['skipped'] if r['reason'] == 'requires_individual_review']
    plan['status'] = 'needs_review' if plan['needs_review'] else 'ready'
    plan['preview'] = preview(plan)
    return plan


def preview(plan):
    """Compact path/category/action summary suitable for CLI or settings UI."""
    rows = []
    for group, action in [('entries','import'), ('conflicts','conflict'), ('skipped','preserve')]:
        for entry in plan[group]:
            path = destination_path(plan, entry)
            rows.append({'path':entry['path'], 'target':str(path), 'category':entry['category'],
                         'action':'replace' if action=='import' and entry.get('previous_sha256') else action,
                         'reason':entry.get('reason'), 'bytes':entry.get('size',0),
                         'executable_content':entry['category'] in ('shell','aliases','plugins')})
    return {'schema_version': SCHEMA_VERSION, 'files':rows,
            'excluded':plan['excluded'], 'account_action':plan['account_action'],
            'filtered_associations':plan.get('filtered_associations', []),
            'execution':'Imported shell and plugin code is never executed by file migration.'}


def text_diff(plan, relative):
    """Bounded, on-demand diff; binary/large files are reviewed by metadata."""
    entry = next((e for key in ('entries','conflicts','skipped') for e in plan[key] if e['path']==relative), None)
    if entry is None: raise ValueError('Path is not in the reviewed plan')
    source = _read(source_path(plan, entry))[0]
    target = destination_path(plan, entry)
    before = _read(target)[0] if target.exists() else b''
    if len(source) > MAX_PREVIEW_BYTES or len(before) > MAX_PREVIEW_BYTES:
        return {'kind':'metadata', 'reason':'file_too_large', 'source_bytes':len(source),'target_bytes':len(before)}
    try:
        old = before.decode('utf-8')
        new = entry.get('content_override', source.decode('utf-8'))
        if '\0' in old or '\0' in new: raise UnicodeError('binary file')
    except UnicodeError:
        return {'kind':'metadata', 'reason':'binary_file', 'source_bytes':len(source),'target_bytes':len(before)}
    return {'kind':'text', 'diff':''.join(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),
                                                           fromfile='current/'+relative,tofile='import/'+relative))}

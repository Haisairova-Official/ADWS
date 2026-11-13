"""Inspect and manage the SDDM login theme from ADWS Settings."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

if __name__ == '__main__':
    # Isolated Python excludes the script directory. Import only our siblings.
    sys.path.append(str(Path(__file__).resolve().parent))

import adws_install_boot_themes as boot


class AuthorizationCancelled(RuntimeError):
    pass


def _snapshot(root, runner):
    report = boot.detect(root, runner, login_only=True)
    manager = report['login_manager']
    sddm = report['sddm']
    inputs = {}
    warnings = list(report['warnings'])
    fragment = ''
    exists = False
    try:
        for path in set(report['inputs']):
            inputs[path] = boot._state(boot._system(root, path))
        target = boot._system(root, boot.SDDM_FRAGMENT)
        exists = target.exists()
        fragment = boot._read(root, boot.SDDM_FRAGMENT)
    except (OSError, UnicodeError, ValueError) as error:
        warnings.append(str(error))
    managed = exists and boot.owned_sddm_fragment(fragment)
    revision_data = [manager, sddm, inputs, sorted(warnings)]
    revision = hashlib.sha256(json.dumps(revision_data, sort_keys=True).encode()).hexdigest()
    blockers = []
    if sddm['shadowing_current'] is not None:
        blockers.append('/etc/sddm.conf')
    blockers.extend(sddm.get('later_overrides', []))

    selected = manager['id'] == 'sddm'
    if warnings:
        message, detail = '无法完整读取登录配置：{}', '；'.join(warnings)
    elif not selected:
        message, detail = '只有使用 SDDM 登录时才能接管主题。', ''
    elif exists and not managed:
        message, detail = '此文件包含自定义设置，请先检查：{}', boot.SDDM_FRAGMENT
    elif blockers:
        message, detail = '此文件的主题设置优先于 ADWS：{}', '、'.join(blockers)
    elif not sddm['themes']:
        message, detail = '未找到已安装的 SDDM 主题。', ''
    else:
        message, detail = '', ''
    return {
        'manager': manager['id'], 'manager_name': manager['name'],
        'active': manager['active'], 'configured': manager['configured'],
        'current': sddm['current'], 'themes': sddm['themes'], 'managed': managed,
        'can_apply': not message, 'can_restore': selected and managed and not warnings,
        'override_path': boot.SDDM_FRAGMENT, 'revision': revision,
        'reason': message, 'detail': detail,
    }


def inspect(root=Path('/'), runner=subprocess.run):
    from adws_i18n import tr
    snapshot = _snapshot(Path(root), runner)
    snapshot['conflict'] = tr(snapshot['reason']).format(snapshot['detail']) if snapshot['reason'] else ''
    return snapshot


def _perform(request, root, runner):
    if not isinstance(request, dict) or request.keys() != {'action', 'theme', 'revision'}:
        raise ValueError('Invalid SDDM settings request')
    action, theme, revision = (request[key] for key in ('action', 'theme', 'revision'))
    if (action not in ('apply', 'restore') or not isinstance(theme, str) or
        (action == 'restore' and theme) or (action == 'apply' and not boot.NAME.fullmatch(theme)) or
        not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision)):
        raise ValueError('Invalid SDDM settings request')
    state = _snapshot(root, runner)
    if state['revision'] != revision:
        raise ValueError('登录配置已改变，请刷新后重试。')
    if not state['can_' + action] or (action == 'apply' and theme not in state['themes']):
        raise ValueError('当前登录配置不支持此操作，请刷新后重试。')
    proposal = boot.plan(login_theme=theme if action == 'apply' else 'preserve',
                         login_only=True, release_login=action == 'restore',
                         root=root, runner=runner)
    if proposal['conflicts']:
        raise ValueError('\n'.join(proposal['conflicts']))
    if _snapshot(root, runner)['revision'] != revision:
        raise ValueError('登录配置已改变，请刷新后重试。')
    backup = root / boot.BACKUP_ROOT.relative_to('/') / uuid.uuid4().hex
    return boot.apply(proposal, backup, runner=runner)


def _change(action, theme, snapshot):
    from adws_i18n import tr
    if not snapshot['can_' + action]:
        raise ValueError(snapshot['conflict'] or tr('当前登录配置不支持此操作，请刷新后重试。'))
    if action == 'apply' and theme not in snapshot['themes']:
        raise ValueError(tr('请选择已安装的 SDDM 主题。'))
    command = ['/usr/bin/python3', '-I', str(Path(__file__).resolve()), '--change']
    if os.geteuid() != 0:
        if not Path('/usr/bin/pkexec').is_file():
            raise RuntimeError(tr('未安装 pkexec，请安装 polkit 并启用系统认证代理。'))
        command[:0] = ['/usr/bin/pkexec', '--disable-internal-agent']
    request = {'action': action, 'theme': theme, 'revision': snapshot['revision']}
    reply = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
    if reply.returncode == 126:
        raise AuthorizationCancelled(tr('已取消授权。'))
    if reply.returncode == 127:
        raise RuntimeError(tr('未取得管理员授权，请检查系统认证代理。'))
    if reply.returncode:
        raise RuntimeError(tr(reply.stderr.strip() or 'SDDM 主题设置失败。'))
    return json.loads(reply.stdout)


def apply(theme, snapshot):
    return _change('apply', theme, snapshot)


def restore(snapshot):
    return _change('restore', '', snapshot)


if __name__ == '__main__':
    if sys.argv[1:] != ['--change'] or os.geteuid() != 0:
        raise SystemExit('The SDDM settings helper requires administrator authorization.')
    try:
        request = json.loads(sys.stdin.buffer.read(2048))
        print(json.dumps(_perform(request, Path('/'), subprocess.run)))
    except (ValueError, OSError, RuntimeError) as error:
        raise SystemExit(str(error))

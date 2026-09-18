"""Read-only GitHub Release checks shared by CLI and GTK settings."""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from mnws_i18n import tr as _tr, message

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = 'Haisairova-Official/MNWS'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
COUNTRY_API = 'https://api.country.is/'
DEFAULT_PROXY = 'https://gh-proxy.com/'


def read_json(url, timeout=5):
    request = urllib.request.Request(url, headers={'User-Agent': 'MNWS-update-check', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError('Response exceeds size limit')
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    return data


def mainland_china():
    try:
        return read_json(COUNTRY_API, timeout=2).get('country') == 'CN'
    except (OSError, ValueError):
        return False


def version_key(text):
    # MNWS's Major is a decimal (1.20 -> 1.30), followed by letter-based Minor.
    match = re.fullmatch(r'v?(\d+\.\d+)(?:\.(\d+))?(?:[\s_-]*(Pre-release|Released?|[A-Za-z]))?', text.strip(), re.I)
    if not match:
        raise ValueError(_tr('无法识别版本号：%s') % text)
    major, patch, minor = match.groups()
    rank = 27 if minor is None or minor.lower() in ('release', 'released') else 26.5 if minor.lower() == 'pre-release' else ord(minor.upper()) - ord('A') + 1
    return Decimal(major), int(patch or 0), rank


def current_version():
    info = json.loads((ROOT / 'build-info.json').read_text())
    suffix = info.get('release_label') or info.get('minor_version') or 'Release'
    return f"{info['major_version']} {suffix}"


def check_update():
    current = version_key(current_version())
    urls = [API]
    if mainland_china():
        proxy = os.environ.get('MNWS_GITHUB_PROXY', DEFAULT_PROXY).strip()
        parsed = urllib.parse.urlparse(proxy)
        if parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
            urls.insert(0, proxy.rstrip('/') + '/' + API)
    errors = []
    for url in urls:
        try:
            release = read_json(url)
            if release.get('draft') or release.get('prerelease'):
                raise ValueError(_tr('更新源未返回正式 Release。'))
            tag = release.get('tag_name')
            if not isinstance(tag, str):
                raise ValueError(_tr('更新源缺少版本号。'))
            remote = version_key(tag)
            name = release.get('name')
            if isinstance(name, str):
                try:
                    named_version = version_key(name)
                    if named_version[:2] == remote[:2]:
                        remote = named_version
                except ValueError:
                    pass
            if remote <= current:
                return {'available': False, 'text': message('updates.none'), 'url': None}
            link = f'https://github.com/{REPOSITORY}/releases/tag/' + urllib.parse.quote(tag, safe='')
            return {'available': True, 'text': _tr('发现新版本：%s') % tag, 'url': link}
        except (OSError, ValueError) as error:
            errors.append(str(error))
    raise RuntimeError(_tr('检查更新失败，请检查网络后重试。') + '\n' + '\n'.join(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description=_tr('检查 GitHub 上的正式 Release，不自动安装。'))
    parser.parse_args(argv)
    try:
        result = check_update()
        print(result['text'])
        if result['url']:
            print(result['url'])
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

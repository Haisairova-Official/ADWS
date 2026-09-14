"""Normalize MNWS's single default include without rewriting user include lists."""
from mnws_i18n import tr as _tr
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


def normalize_default_include(config, config_path):
    value = config.get('include')
    candidate = value[0] if isinstance(value, list) and len(value) == 1 else value
    if not isinstance(candidate, str):
        return False
    parent = Path(config_path).absolute().parent
    expanded = Path(os.path.expandvars(candidate)).expanduser()
    expanded = Path(os.path.abspath(parent / expanded))
    default = parent / 'modules.jsonc'
    if expanded != default or value == str(default):
        return False
    config['include'] = str(default)
    return True


def update_installed_config(path):
    from mnws_layout import parse_jsonc
    path = Path(path).absolute()
    original = path.read_text()
    config = parse_jsonc(original)
    if not normalize_default_include(config, path):
        return False
    # Locate only the top-level value; retain comments, spacing and other settings.
    tokens = list(re.finditer(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|[^\s]', original, re.S))
    tokens = [token for token in tokens if not token.group().startswith(('//', '/*'))]
    depth = 0
    for index, token in enumerate(tokens):
        text = token.group()
        if depth == 1 and text.startswith('"') and json.loads(text) == 'include' and tokens[index + 1].group() == ':':
            start = tokens[index + 2]
            end = start
            if start.group() == '[':
                end = next(item for item in tokens[index + 3:] if item.group() == ']')
            comments = [item.group() for item in re.finditer(
                r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                original[start.start():end.end()], re.S)
                if item.group().startswith(('//', '/*'))]
            prefix = ''.join(comment + '\n' for comment in comments)
            updated = original[:start.start()] + prefix + json.dumps(config['include'], ensure_ascii=False) + original[end.end():]
            break
        if text in ('{', '['):
            depth += 1
        elif text in ('}', ']'):
            depth -= 1
    else:
        raise ValueError(_tr('无法定位顶层 include 配置'))
    # Preserve an existing config symlink and back up its content before updating.
    target = path.resolve(strict=True)
    backup = path.with_name(path.name + '.mnws-include-bak')
    if not backup.exists():
        shutil.copy2(target, backup)
    fd, temporary = tempfile.mkstemp(prefix='.mnws-include-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(updated)
        os.chmod(temporary, target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


if __name__ == '__main__':
    import sys
    try:
        update_installed_config(sys.argv[1])
    except (OSError, ValueError) as error:
        print(''.join([_tr('include 配置更新失败：'), f'{error}']), file=sys.stderr)
        raise SystemExit(1)

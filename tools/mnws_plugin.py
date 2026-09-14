#!/usr/bin/env python3
"""mnws-plugin — .mplg 插件包工具（drop-in 模式）

.mplg = zip，内含 plugin.json 与本体实现。把 .mplg 直接丢进插件目录即可被
MNWS 扫描加载，不需要“安装/注册”。规范见 docs/mplg-spec.md。
"""
from __future__ import annotations
from mnws_i18n import tr as _tr

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import hashlib
import fcntl
import stat
import mnws_plugin_api as api1
from pathlib import Path

MANIFEST = "plugin.json"
API_NAME = "mnws-plugin"
API_VERSION = 1

KINDS = {"panel", "desktop", "menu", "utility"}
LANGUAGES = {"python", "shell", "binary"}
INTERFACES = {"panel.json-v1", "panel.rows-v1", "desktop.json-v1"}
SLOTS = {"left", "center", "right"}

ID_RE = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")

PACK_EXTRA = {".pyc", ".pyo", "__pycache__"}
SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache"}

EXAMPLE_PLUGIN_JSON = _tr('{\n  "api": "mnws-plugin",\n  "apiVersion": 1,\n  "id": "org.mnws.hello",\n  "name": "Hello",\n  "version": "0.1.0",\n  "kind": "panel",\n  "language": "python",\n  "entry": "main.py",\n  "interfaces": ["panel.json-v1"],\n  "author": "",\n  "description": "任务栏示例插件（panel.json-v1）",\n  "license": "MIT",\n  "defaults": {\n    "slot": "right",\n    "width": 0,\n    "interval": 1.0\n  }\n}\n')

EXAMPLE_MAIN_PY = _tr('#!/usr/bin/env python3\n"""MNWS panel.json-v1 示例插件。\n\n--output-json  向 stdout 打印一行 JSON（宿主要求）\n--click <键>    处理点击（可选，可空实现）\n"""\nimport argparse\nimport json\nfrom datetime import datetime\n\n\ndef render() -> dict:\n    now = datetime.now()\n    return {\n        "text": "\\U0001f44b",\n        "alt": "hello",\n        "class": "normal",\n        "tooltip": "Hello MNWS\\n%s" % now.strftime("%Y-%m-%d %H:%M:%S"),\n    }\n\n\ndef main(argv=None) -> int:\n    parser = argparse.ArgumentParser(description="MNWS panel plugin")\n    parser.add_argument("--output-json", action="store_true")\n    parser.add_argument("--click", choices=("left", "right", "middle",\n                                            "scroll-up", "scroll-down"))\n    args = parser.parse_args(argv)\n    if args.click:\n        return 0  # 示例插件不响应点击\n    payload = render()\n    print(json.dumps(payload, ensure_ascii=False))\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n')


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def plugin_dir() -> Path:
    """扫描目录：用户把 .mplg 直接丢进来。"""
    override = os.environ.get("MNWS_PLUGIN_DIR")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "mnws/plugins"


def cache_dir() -> Path:
    """运行缓存：zip 里的入口没法直接执行，宿主按需解包到这里。"""
    override = os.environ.get("MNWS_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "mnws/plugins"


def scan_packages(folder: Path | None = None) -> list[Path]:
    folder = folder or plugin_dir()
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.glob("*.mplg") if path.is_file())


def archive_name(manifest: dict) -> str:
    return "%s_%s.mplg" % (manifest["id"], manifest["version"])


def safe_members(names: list[str]) -> list[str]:
    members = []
    for raw in names:
        name = raw.replace("\\", "/")
        if not name or name.startswith("/") or ".." in Path(name).parts:
            continue
        members.append(name)
    return sorted(set(members))


def validate_manifest(manifest, members: set[str] | None = None) -> list[str]:
    errors = []
    if not isinstance(manifest, dict):
        return [_tr('plugin.json 必须是 JSON 对象')]
    if "renderer" in manifest:
        errors.extend(api1.public_errors(manifest))
        manifest = api1.normalize(manifest)
    errors.extend(api1.schema_errors(manifest.get("settingsSchema", [])))
    if manifest.get("api") != API_NAME:
        errors.append(_tr('api 必须为 "%s"') % API_NAME)
    if type(manifest.get("apiVersion")) is not int or manifest.get("apiVersion") != API_VERSION:
        errors.append(_tr('apiVersion 必须为 %d') % API_VERSION)
    for key in ("id", "name", "version", "kind", "language", "entry"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            errors.append(_tr('缺少字符串字段 %s') % key)
    if not errors:
        if not api1.ID.fullmatch(manifest["id"]):
            errors.append(_tr('id 必须为小写反向域名风格，如 org.mnws.hello'))
        if not VERSION_RE.fullmatch(manifest["version"]):
            errors.append(_tr('version 必须为 主.次.修订 或带 -pre 后缀'))
        if manifest["kind"] not in KINDS:
            errors.append(_tr('kind 必须是 %s 之一') % ", ".join(sorted(KINDS)))
        if manifest["language"] not in LANGUAGES:
            errors.append(_tr('language 必须是 %s 之一') % ", ".join(sorted(LANGUAGES)))
        entry = manifest["entry"]
        if not api1.safe_path(entry):
            errors.append(_tr('entry 必须是包内相对路径，禁止绝对路径或 ..'))
        if members is not None and entry not in members:
            errors.append(_tr('entry %r 不在包内') % entry)
    interfaces = manifest.get("interfaces")
    if interfaces is not None:
        if not isinstance(interfaces, list) or not all(
            isinstance(item, str) for item in interfaces
        ):
            errors.append(_tr('interfaces 必须是字符串数组'))
        else:
            unknown = sorted(set(interfaces) - INTERFACES)
            if unknown:
                errors.append(_tr('未知接口: %s') % ", ".join(unknown))
    defaults = manifest.get("defaults")
    if defaults is not None:
        if not isinstance(defaults, dict):
            errors.append(_tr('defaults 必须是对象'))
        else:
            slot = defaults.get("slot")
            if slot is not None and (not isinstance(slot, str) or slot not in SLOTS):
                errors.append(_tr('defaults.slot 必须是 left/center/right'))
    return errors


def load_manifest(path: Path) -> dict:
    if not path.is_file() or path.suffix.lower() != ".mplg":
        raise ValueError(_tr('不是 .mplg 文件: %s') % path)
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(MANIFEST)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError(_tr('无法读取 %s: %s') % (MANIFEST, exc))
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(raw.decode("utf-8"))
            errors = validate_manifest(manifest)
            if errors: raise ValueError('; '.join(errors))
            return api1.localized(manifest, archive)
    except ValueError as exc:
        raise ValueError(_tr('plugin.json 不是合法 JSON: %s') % exc)


def validate_package(path: Path) -> tuple[bool, list[str], dict | None]:
    if not path.is_file() or path.suffix.lower() != ".mplg":
        return False, [_tr('不是 .mplg 文件')], None
    errors = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            members = []
            for info in infos:
                name = info.filename
                if not api1.safe_path(name) or stat.S_ISLNK(info.external_attr >> 16):
                    errors.append(_tr('非法路径: %s') % name)
                if name in members:
                    errors.append('Duplicate ZIP member: ' + name)
                members.append(name)
            if MANIFEST not in members:
                return False, [_tr('包内缺少 plugin.json')], None
            if errors:
                return False, errors, None
            try:
                manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
            except (ValueError, KeyError) as exc:
                return False, [_tr('plugin.json 无法解析：%s') % exc], None
            errors = validate_manifest(manifest, members={i.filename for i in infos if not i.is_dir()})
            if errors:
                return False, errors, manifest
            if sum(info.file_size for info in infos) > 200 * 1024 * 1024:
                return False, [_tr('包超过 200 MiB 上限')], manifest
            try:
                for locale_name in ('locale/zh.json', 'locale/en.json'):
                    if locale_name in members:
                        table = json.loads(archive.read(locale_name).decode('utf-8'))
                        if not isinstance(table, dict) or any(not isinstance(v, str) for v in table.values()):
                            raise ValueError('Plugin locale must contain strings')
                manifest = api1.localized(manifest, archive)
            except (ValueError, UnicodeError, TypeError) as error:
                return False, [str(error)], None
            return True, [], manifest
    except zipfile.BadZipFile:
        return False, [_tr('不是合法 zip')], None


def collect_source_files(source: Path) -> list[str]:
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError('Plugin sources must not contain symbolic links')
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.suffix in PACK_EXTRA or path.name == MANIFEST + ".tmp":
            continue
        files.append(str(rel).replace(os.sep, "/"))
    return files


def build_package(source: Path, output: Path | None = None) -> Path:
    source = source.resolve()
    if not (source / MANIFEST).is_file():
        raise SystemExit(_tr('错误：%s 下找不到 plugin.json') % source)
    try:
        manifest = json.loads((source / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(_tr('错误：plugin.json 无法解析：%s') % exc)
    files = collect_source_files(source)
    errors = validate_manifest(manifest, members=set(files))
    for name in files:
        if not api1.safe_path(name): errors.append('Invalid source path: ' + name)
    for name in ('locale/zh.json', 'locale/en.json'):
        if name in files:
            try:
                table = json.loads((source / name).read_text(encoding='utf-8'))
                if not isinstance(table, dict) or any(not isinstance(value, str) for value in table.values()):
                    errors.append('Plugin locale must contain strings')
            except (OSError, ValueError) as error:
                errors.append(str(error))
    if errors:
        raise SystemExit(_tr('校验失败：\n') + "\n".join(" - " + item for item in errors))
    if output is None:
        output = source.parent / archive_name(manifest)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staged = Path(tmp) / "pkg"
        staged.mkdir()
        for name in files:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
        temp_zip = staged.with_suffix(".mplg")
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in collect_source_files(staged):
                archive.write(staged / name, arcname=name)
        shutil.move(str(temp_zip), str(output))
    return output


def materialize(path: Path, cache: Path | None = None) -> Path:
    cache = cache or cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / '.materialize.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _materialize(path, cache)


def _materialize(path: Path, cache: Path | None = None) -> Path:
    """把 .mplg 解包到缓存并返回入口目录；zip 更新后自动重建。"""
    ok, errors, manifest = validate_package(path)
    if not ok:
        raise ValueError("；".join(errors))
    manifest = load_manifest(path)
    cache = cache or cache_dir()
    dest = cache / manifest["id"] / manifest["version"]
    stamp = dest / ".mnws-stamp.json"
    try:
        mtime = path.stat().st_mtime
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(_tr('无法读取 %s: %s') % (path, exc))
    fresh = False
    if stamp.is_file():
        try:
            data = json.loads(stamp.read_text(encoding="utf-8"))
            fresh = data.get("sha256") == digest and (dest / manifest["entry"]).is_file()
        except (OSError, ValueError):
            fresh = False
    if fresh:
        return dest
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as archive:
            for name in safe_members([info.filename for info in archive.infolist()]):
                if archive.getinfo(name).is_dir():
                    continue
                target = dest / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        entry = dest / manifest["entry"]
        if entry.is_file():
            os.chmod(entry, 0o755)
        stamp.write_text(json.dumps({
            "source": str(path.resolve()),
            "mtime": mtime,
            "sha256": digest,
            "size": path.stat().st_size,
            "id": manifest["id"],
            "version": manifest["version"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def copy_into(folder: Path, path: Path, replace: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    if target.exists() and not replace:
        raise FileExistsError(_tr('%s 已存在') % target)
    shutil.copy2(path, target)
    return target


def cmd_init(args) -> int:
    target = Path(args.directory).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        print(_tr('错误：目录非空：%s') % target, file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-z0-9]", "", target.name.lower())
    pkg_id = args.id or ("org.mnws." + stem if stem else "org.mnws.plugin")
    manifest = json.loads(EXAMPLE_PLUGIN_JSON)
    manifest.update(renderer='panel.text-v1', mnws={'api': 1, 'minVersion': '1.25'})
    for key in ('api', 'apiVersion', 'kind', 'language', 'interfaces'):
        manifest.pop(key, None)
    manifest["id"] = pkg_id
    if args.name:
        manifest["name"] = args.name
    (target / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "main.py").write_text((project_root() / 'plugins/sample/main.py').read_text(), encoding="utf-8")
    (target / "README.md").write_text(
        _tr('# %s\n\nMNWS %s 插件。运行 `mnws mplg build %s` 打包，\n然后把生成的 .mplg 丢到 `mnws mplg dir` 显示的文件夹即可。\n')
        % (manifest["name"], 'panel', target), encoding="utf-8"
    )
    print(_tr('已创建插件源：%s') % target)
    print(_tr('打包：mnws mplg build %s') % target)
    return 0


def cmd_build(args) -> int:
    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(_tr('错误：目录不存在：%s') % source, file=sys.stderr)
        return 2
    output = Path(args.output).expanduser().resolve() if args.output else None
    try:
        built = build_package(source, output)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(_tr('已打包：%s') % built)
    print(_tr('把它丢进 %s 即可被 MNWS 扫描加载。') % plugin_dir())
    return 0


def cmd_validate(args) -> int:
    path = Path(args.package).expanduser().resolve()
    ok, errors, manifest = validate_package(path)
    if ok:
        print("OK：%s  %s %s" % (path, manifest["id"], manifest["version"]))
        return 0
    print(_tr('无效：%s') % path, file=sys.stderr)
    for item in errors:
        print(" - %s" % item, file=sys.stderr)
    return 1


def cmd_inspect(args) -> int:
    path = Path(args.package).expanduser().resolve()
    ok, errors, _ = validate_package(path)
    if not ok:
        print(_tr('无效：%s') % path, file=sys.stderr)
        for item in errors:
            print(" - %s" % item, file=sys.stderr)
        return 1
    print(json.dumps(load_manifest(path), ensure_ascii=False, indent=2))
    return 0


def cmd_dir(_args) -> int:
    print(plugin_dir())
    return 0


def cmd_add(args) -> int:
    path = Path(args.package).expanduser().resolve()
    ok, errors, _ = validate_package(path)
    if not ok:
        print(_tr('无效：%s') % path, file=sys.stderr)
        for item in errors:
            print(" - %s" % item, file=sys.stderr)
        return 1
    target = copy_into(plugin_dir(), path)
    print(_tr('已放入扫描目录：%s') % target)
    return 0


def cmd_remove(args) -> int:
    folder = plugin_dir()
    targets = []
    for path in scan_packages(folder):
        try:
            manifest = load_manifest(path)
            if api1.canonical_id(manifest['id']) == api1.canonical_id(args.filename) or path.name == args.filename:
                targets.append(path)
        except (ValueError, OSError):
            if path.name == args.filename: targets.append(path)
    if not targets:
        print(_tr('不存在：%s') % args.filename, file=sys.stderr)
        return 1
    for target in targets:
        target.unlink()
        print(_tr('已删除：%s') % target)
    return 0


def cmd_list(_args) -> int:
    folder = plugin_dir()
    if not folder.is_dir():
        print(_tr('（插件目录尚不存在：%s）') % folder)
        return 0
    files = scan_packages(folder)
    if not files:
        print(_tr('（空：把 .mplg 丢到 %s）') % folder)
        return 0
    for path in files:
        ok, errors, manifest = validate_package(path)
        if ok:
            print("%s  %-12s v%-9s %s  %s" % (
                "OK ", manifest["kind"], manifest["version"],
                manifest["name"], path.name))
        else:
            print("ERR %-17s %s  (%s)" % ("?", "?", path.name, errors[0]))
    return 0


def resolve_package(ref: str) -> Path:
    """ref 可以是 .mplg 路径，也可以是目录里的包 id 或文件名。"""
    candidate = Path(ref).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    folder = plugin_dir()
    matches = []
    for path in scan_packages(folder):
        if path.name == ref:
            return path
        try:
            manifest = load_manifest(path)
        except ValueError:
            continue
        if api1.canonical_id(manifest["id"]) == api1.canonical_id(ref):
            matches.append((api1.package_version(manifest['version']), path))
    if matches: return max(matches)[1]
    raise SystemExit(_tr('找不到 .mplg：%s（目录：%s）') % (ref, folder))


def cmd_run(args) -> int:
    try:
        path = resolve_package(args.ref)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    ok, errors, _ = validate_package(path)
    if not ok:
        print(_tr('无效：%s') % path, file=sys.stderr)
        for item in errors:
            print(" - %s" % item, file=sys.stderr)
        return 1
    try:
        root = materialize(path)
        manifest = load_manifest(path)
    except ValueError as exc:
        print(_tr('准备运行失败：%s') % exc, file=sys.stderr)
        return 1
    if manifest["language"] != "python":
        print(_tr('当前 run 仅支持 python 插件'), file=sys.stderr)
        return 1
    from mnws_plugin_runner import execute
    try:
        return execute(root, manifest, json.loads(args.settings_json), timeout=float(args.timeout))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(
        prog="mnws-plugin",
        description=_tr('.mplg 插件包工具：init / build / validate / 目录扫描'),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help=_tr('生成插件源脚手架'))
    p.add_argument("directory")
    p.add_argument("--id", help=_tr('插件 id（默认 org.mnws.<目录名>）'))
    p.add_argument("--name", help=_tr('显示名'))
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("build", help=_tr('把插件目录打包成 .mplg'))
    p.add_argument("source")
    p.add_argument("-o", "--output", help=_tr('输出路径'))
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("validate", help=_tr('校验 .mplg'))
    p.add_argument("package")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("inspect", help=_tr('查看 .mplg 的 plugin.json'))
    p.add_argument("package")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("dir", help=_tr('打印插件扫描目录'))
    p.set_defaults(func=cmd_dir)

    p = sub.add_parser("add", aliases=["install"], help=_tr('把一个 .mplg 复制进扫描目录'))
    p.add_argument("package")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", help=_tr('从扫描目录删除文件'))
    p.add_argument("filename")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("list", help=_tr('列出扫描目录中的 .mplg'))
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("run", help=_tr('试跑已就位的 .mplg（--output-json）'))
    p.add_argument("ref", help=_tr('.mplg 路径 / 文件名 / 包 id'))
    p.add_argument("--timeout", default=10.0)
    p.add_argument("--settings-json", default="{}")
    p.set_defaults(func=cmd_run)

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = arguments(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

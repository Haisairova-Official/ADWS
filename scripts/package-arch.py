#!/usr/bin/env python3
"""Build the native libraries and produce a clean Arch x86_64 release ZIP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import sys
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Use only cached Cargo dependencies')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/ADWS1.35_for_arch.zip')
    args = parser.parse_args()
    if platform.machine() != 'x86_64' or platform.freedesktop_os_release().get('ID') != 'arch':
        parser.error('Build this package on Arch Linux x86_64')
    sys.path.insert(0, str(ROOT/'tools'))
    from adws_setup import build_environment, choose_build_mirror, cargo_build_command
    build_env = build_environment()
    if not args.offline: build_env = choose_build_mirror(build_env)
    build_env = {key: value for key, value in build_env.items() if key != 'CARGO_TARGET_DIR'}
    cargo = cargo_build_command(build_env) + ['--manifest-path', str(ROOT/'src/niri-taskbar/Cargo.toml')]
    if args.offline: cargo.append('--offline')
    subprocess.run(cargo, check=True, env=build_env)
    runtime_cargo = cargo_build_command(build_env) + ['--manifest-path', str(ROOT/'src/adws-runtime/Cargo.toml')]
    if args.offline: runtime_cargo.append('--offline')
    subprocess.run(runtime_cargo, check=True, env=build_env)
    menu_cargo = cargo_build_command(build_env) + ["--manifest-path", str(ROOT/"src/adws-start-menu/Cargo.toml")]
    if args.offline: menu_cargo.append("--offline")
    subprocess.run(menu_cargo, check=True, env=build_env)
    subprocess.run(['make', '-C', str(ROOT/'src/panel-rows')], check=True)
    with tempfile.TemporaryDirectory(prefix='adws-arch-package-') as temporary:
        stage = Path(temporary) / args.output.stem
        stage.mkdir()
        # Stage only Git-tracked source, including reviewed additions in the index.
        # Native binaries are injected explicitly below after their release builds.
        files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        # Font fallback migration is required by the generated layout and topbar.
        # Include it explicitly even in a working checkout before git staging.
        files.extend(['tools/adws_popup_effect.py', 'src/niri-desktop-layer/integration/popup-effect.c', 'tools/adws_clipboard_pins.py', 'tools/adws_clipboard_preview.py', 'tools/adws_clipboard_gui.py', 'tools/adws_agenda.py', 'tools/adws_calendar.py', 'tools/adws_weather.py', 'tools/adws_agenda_preview.py', 'tools/adws_location.py', 'tools/adws_location_registration.py', 'tools/adws_tides.py', 'tools/adws_ocean.py', 'tools/adws_control_center.py', 'tools/adws_popup.py', 'tools/adws_fonts.py', 'tools/adws_app_scaling.py', 'tools/adws_sidebar.py', 'tools/adws_sidebar_widgets.py', 'tools/adws_sidebar_model.py', 'tools/adws_sidebar_board.py', 'tools/adws_sidebar_notifications.py', 'src/niri-desktop-layer/desktop_layer/open_with.py'])
        if not (ROOT/'tools/adws_fonts.py').is_file():
            raise RuntimeError('Missing required font migration module')
        roots = {'patches', 'config', 'docs', 'language', 'plugins', 'samples', 'scripts', 'src', 'tools', 'vendor'}
        top_files = {'adws','install.sh','README.md','Language.md','CHANGELOG.md','LICENSE','THIRD_PARTY_NOTICES.md','build-info.json','.gitignore'}
        excluded = {'target','__pycache__','.cache','.git','state','node_modules'}
        hashes = {}
        for name in sorted(set(files)):
            if not name: continue
            relative = Path(name)
            if name not in top_files and relative.parts[0] not in roots: continue
            if excluded.intersection(relative.parts) or relative.suffix in ('.pyc','.so','.o'): continue
            if any(part.startswith('.') for part in relative.parts) and name != '.gitignore': continue
            source = ROOT/relative
            if not source.is_file(): continue
            destination = stage/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source,destination)
            hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        folder=stage/'prebuilt';folder.mkdir()
        for name, source in [('libniri_taskbar.so', ROOT/'src/niri-taskbar/target/release/libniri_taskbar.so'), ('libadws_panel.so',ROOT/'src/panel-rows/libadws_panel.so')]:
            shutil.copy2(source,folder/name)
        flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gtk+-3.0','gtk-layer-shell-0','wayland-client'],text=True))
        subprocess.run(['cc','-shared','-fPIC','-O2',str(ROOT/'src/niri-desktop-layer/integration/waybar-space.c'),'-o',str(folder/'libwaybar-space.so'),*flags,'-lm'],check=True)
        shutil.copy2(ROOT/'src/adws-runtime/target/release/adws-plugin-runner', folder/'adws-plugin-runner')
        shutil.copy2(ROOT/'src/adws-start-menu/target/release/adws-start-menu', folder/'adws-start-menu')
        libraries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
        metadata = json.loads((ROOT / 'build-info.json').read_text())
        manifest={'version':metadata.get('display_version') or metadata['major_version'] + ' ' + metadata['release_label'],'os':'arch','arch':'x86_64','internal_revision':metadata.get('minor_version'),'sha256':libraries,
                  'source_tree_sha256':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()}
        (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        shutil.copy2(ROOT/'docs/arch-install.md',stage/'ARCH-INSTALL.md')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(stage.rglob('*')):
                if file.is_file():archive.write(file,str(file.relative_to(stage.parent)))
    checksum=hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.zip.sha256').write_text(f'{checksum}  {args.output.name}\n')
    print(args.output)
    print(checksum)


if __name__ == '__main__':
    main()

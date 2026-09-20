#!/usr/bin/env python3
"""Build the native libraries and produce a clean Arch x86_64 release ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Use only cached Cargo dependencies')
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'MNWS1.25_for_arch.zip')
    args = parser.parse_args()
    if platform.machine() != 'x86_64' or platform.freedesktop_os_release().get('ID') != 'arch':
        parser.error('Build this package on Arch Linux x86_64')
    cargo = ['cargo', 'build', '--release', '--locked', '--manifest-path', str(ROOT/'src/niri-taskbar/Cargo.toml')]
    if args.offline: cargo.append('--offline')
    subprocess.run(cargo, check=True)
    subprocess.run(['make', '-C', str(ROOT/'src/panel-rows')], check=True)
    with tempfile.TemporaryDirectory(prefix='mnws-arch-package-') as temporary:
        stage = Path(temporary) / 'MNWS1.25_for_arch'
        stage.mkdir()
        # Release archives are reproducible: only committed source files are staged.
        # Native binaries are injected explicitly below after their release builds.
        files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        roots = {'config', 'docs', 'language', 'plugins', 'samples', 'scripts', 'src', 'tools', 'vendor'}
        top_files = {'mnws','install.sh','README.md','Language.md','CHANGELOG.md','LICENSE','THIRD_PARTY_NOTICES.md','build-info.json','.gitignore'}
        excluded = {'target','__pycache__','.cache','.git','state','node_modules'}
        hashes = {}
        for name in sorted(set(files)):
            if not name: continue
            relative = Path(name)
            if name not in top_files and relative.parts[0] not in roots: continue
            if excluded.intersection(relative.parts) or relative.suffix in ('.pyc','.so','.o','.mplg'): continue
            if any(part.startswith('.') for part in relative.parts) and name != '.gitignore': continue
            source = ROOT/relative
            if not source.is_file(): continue
            destination = stage/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source,destination)
            hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        folder=stage/'prebuilt';folder.mkdir()
        for name, source in [('libniri_taskbar.so', ROOT/'src/niri-taskbar/target/release/libniri_taskbar.so'), ('libmnws_panel.so',ROOT/'src/panel-rows/libmnws_panel.so')]:
            shutil.copy2(source,folder/name)
        flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gtk+-3.0','gtk-layer-shell-0'],text=True))
        subprocess.run(['cc','-shared','-fPIC','-O2',str(ROOT/'src/niri-desktop-layer/integration/waybar-space.c'),'-o',str(folder/'libwaybar-space.so'),*flags],check=True)
        libraries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.so')}
        metadata = json.loads((ROOT / 'build-info.json').read_text())
        manifest={'version':metadata.get('display_version') or metadata['major_version'] + ' ' + metadata['release_label'],'os':'arch','arch':'x86_64','sha256':libraries,
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

#!/usr/bin/env python3
"""Build ADWS native artifacts inside the verified Arch test rootfs only.

Creates an independent source snapshot under the validation directory. Only that
snapshot is writable in the container; development source stays unmounted. No
installer or user-session startup runs. Cargo/make parallelism is capped at 2.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

BUILD = r'''
import hashlib,json,os,shlex,shutil,subprocess
from pathlib import Path
root=Path('/opt/adws');env={**os.environ,'CARGO_BUILD_JOBS':'2','ADWS_BUILD_MIRROR':'0'}
for component in ('niri-taskbar','adws-runtime','adws-start-menu'):
 print('BUILD '+component,flush=True)
 subprocess.run(['cargo','build','--release','--locked','--jobs','2'],cwd=root/'src'/component,env=env,check=True)
subprocess.run(['make','-j2','-C',str(root/'src/panel-rows')],check=True,env=env)
folder=root/'prebuilt';folder.mkdir(exist_ok=True)
flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gtk+-3.0','gtk-layer-shell-0','wayland-client'],text=True))
subprocess.run(['cc','-shared','-fPIC','-O2',str(root/'src/niri-desktop-layer/integration/waybar-space.c'),'-o',str(folder/'libwaybar-space.so'),*flags,'-lm'],check=True)
for name,path in {
 'libniri_taskbar.so':'src/niri-taskbar/target/release/libniri_taskbar.so',
 'libadws_panel.so':'src/panel-rows/libadws_panel.so',
 'adws-plugin-runner':'src/adws-runtime/target/release/adws-plugin-runner',
 'adws-start-menu':'src/adws-start-menu/target/release/adws-start-menu'}.items():shutil.copy2(root/path,folder/name)
checks={}
for file in sorted(folder.iterdir()):
 if file.name=='manifest.json':continue
 result=subprocess.run(['ldd',str(file)],capture_output=True,text=True)
 checks[file.name]={'exit':result.returncode,'output':result.stdout+result.stderr}
 if result.returncode or 'not found' in result.stdout+result.stderr:raise RuntimeError('ELF dependencies unresolved: '+file.name)
libexec=root/'libexec';libexec.mkdir(exist_ok=True)
for name in ('adws-plugin-runner','adws-start-menu'):shutil.copy2(folder/name,libexec/name)
metadata=json.loads((root/'build-info.json').read_text());inputs=json.loads((root/'snapshot-inputs.json').read_text())
manifest={'version':metadata.get('display_version') or metadata['major_version'],
 'os':'arch','arch':'x86_64','internal_revision':metadata.get('minor_version'),'build_version':metadata.get('build_version'),
 'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.name!='manifest.json'},
 'source_tree_sha256':hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest(),
 'validation_environment':'official Arch bootstrap in user namespace; no physical GPU/login validation'}
(folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(root/'native-link-checks.json').write_text(json.dumps(checks,indent=2)+'\n')
print('NATIVE_BUILD_COMPLETE '+json.dumps(manifest,sort_keys=True),flush=True)
'''


def snapshot(source, parent):
    if parent.resolve().is_relative_to(source.resolve()):
        raise ValueError('Snapshot directory must be outside development source')
    destination=parent/datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    parent.mkdir(parents=True,exist_ok=True)
    ignored=shutil.ignore_patterns('.git','target','dist','prebuilt','libexec','__pycache__','.cache','state','node_modules','*.so','*.o','*.pyc')
    shutil.copytree(source,destination,symlinks=True,ignore=ignored)
    inputs={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in destination.rglob('*') if p.is_file() and not p.is_symlink()}
    (destination/'snapshot-inputs.json').write_text(json.dumps(inputs,sort_keys=True,indent=2)+'\n')
    (destination/'snapshot-provenance.json').write_text(json.dumps({'source':str(source),'snapshot':str(destination),
         'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'native artifact build only'},indent=2)+'\n')
    return destination


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--resume-snapshot',type=Path)
    args=parser.parse_args(argv)
    rootfs=args.rootfs.resolve();source=args.source.resolve();parent=rootfs.parent/'native-builds'
    spec=importlib.util.spec_from_file_location('arch_harness',Path(__file__).with_name('check_install_arch_clean.py'))
    harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)
    harness.container_command(rootfs,source,['true'])  # Validate boundaries before copying any source.
    if args.resume_snapshot:
        stage=args.resume_snapshot.resolve()
        if stage.parent!=parent.resolve() or not (stage/'snapshot-provenance.json').is_file():
            raise ValueError('Resume requires a previously created validation snapshot')
        for name,digest in json.loads((stage/'snapshot-inputs.json').read_text()).items():
            path=stage/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError('Snapshot input changed; create a new snapshot: '+name)
    else:stage=snapshot(source,parent)
    command=harness.container_command(rootfs,stage,['python','-c',BUILD])
    mount=command.index(str(stage));assert command[mount-1]=='--ro-bind';command[mount-1]='--bind'
    log=stage/'native-build.log'
    print('Snapshot:',stage,flush=True);print('Build log:',log,flush=True)
    with log.open('a') as output:
        result=subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,timeout=3600)
    (stage/'native-build-result.json').write_text(json.dumps({'exit_code':result.returncode,'log':str(log),
        'max_jobs':2,'environment':'isolated Arch rootfs','installer_executed':False},indent=2)+'\n')
    print('Native build exit:',result.returncode,flush=True)
    return result.returncode


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);raise SystemExit(1)

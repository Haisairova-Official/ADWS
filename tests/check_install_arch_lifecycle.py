#!/usr/bin/env python3
"""Real ADWS installer fixture in the isolated Arch rootfs, never on the host.

A new independent source copy and temporary fixture HOME are created per case.
Native artifacts are reused only after checking their original source hashes.
Plans are programmatically approved solely for this isolated test fixture.
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

CASE = r'''
import json,os,subprocess,sys,time
from pathlib import Path
root=Path('/opt/adws');case=root/'lifecycle-evidence';case.mkdir(exist_ok=True)
sys.path.insert(0,str(root/'tools'))
from adws_install_workflow import execute
plan_process=subprocess.run(['python',str(root/'tools/adws_install_workflow.py'),'--mode','fresh','--plan'],capture_output=True,text=True,timeout=90)
(case/'plan.stdout').write_text(plan_process.stdout);(case/'plan.stderr').write_text(plan_process.stderr)
result={'environment':'root-mapped clean Arch user-space fixture; no physical GPU or normal user login',
        'home':os.environ['HOME'],'cases':[]}
try:
 if plan_process.returncode:raise RuntimeError('Planning failed: '+plan_process.stderr[-1500:])
 plan=json.loads(plan_process.stdout)
 if plan['blocking']:raise RuntimeError('Plan blocked: '+str(plan['blocking']))
 plan['approved']=True
 (case/'approved-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
 if os.environ.get('ADWS_VALIDATION_FAILURE_RESUME')=='1':
  marker=Path(os.environ['XDG_STATE_HOME'])/'adws-validation-fail-once';marker.parent.mkdir(parents=True,exist_ok=True);marker.write_text('fixture only\n')
  try:
   execute(plan,case/'fresh')
  except Exception as expected:
   progress=json.loads((case/'fresh/progress.json').read_text())
   checks={'error':str(expected),'marker_consumed':not marker.exists(),
           'niri_rolled_back':not Path(plan['niri_config_path']).exists(),
           'native_library_rolled_back':not (Path.home()/'.local/lib/waybar/libniri_taskbar.so').exists(),
           'font_directory_rolled_back':not (Path(os.environ['XDG_DATA_HOME'])/'fonts/ADWS-NerdSymbols').exists(),
           'journal_retained':(case/'fresh/progress.json').exists(),
           'package_step_retained':progress.get('steps',{}).get('packages',{}).get('status')=='passed',
           'steps':progress.get('steps')}
   result['cases'].append({'case':'configuration-failure-rollback',**checks})
   if not all(checks[k] for k in ('marker_consumed','niri_rolled_back','native_library_rolled_back','font_directory_rolled_back','journal_retained','package_step_retained')):
    raise RuntimeError('Failure did not restore fixture configuration/native artifacts') from expected
  else:raise RuntimeError('Deliberate configuration failure was not exercised')
 for name,directory in [('fresh',case/'fresh'),('resume',case/'fresh')]:
  started=time.time()
  try:
   code=execute(plan,directory)
   result['cases'].append({'case':name,'exit':code,'seconds':time.time()-started,'report':str(directory)})
   if code not in (0,2):raise RuntimeError('Installer returned failure '+str(code))
   if name=='fresh' and plan.get('package_owner_plan',{}).get('entries'):
    from adws_install_startup import audit
    current=audit(plan['config_home'],plan['niri_config_path'])
    transitions=[]
    for entry in plan['package_owner_plan']['entries']:
     owners=current['owners'].get(entry['component'],[])
     shadow=Path(entry['target'])
     transitions.append({'provider':entry['provider'],'system_entry_created':Path(entry['source']).is_file(),
                         'reviewed_shadow_created':shadow.is_file() and 'Hidden=true' in shadow.read_text(),
                         'owners':owners,'unique_owner':len(owners)==(1 if plan['autostart'] else 0)})
    result['package_startup_transitions']=transitions
    if not all(row['system_entry_created'] and row['reviewed_shadow_created'] and row['unique_owner'] for row in transitions):
     raise RuntimeError('Package-created startup did not reconcile to the reviewed unique ownership')
  except Exception as exc:
   result['cases'].append({'case':name,'error':str(exc),'seconds':time.time()-started})
   raise
 repeated=subprocess.run(['python',str(root/'tools/adws_install_workflow.py'),'--mode','fresh','--plan'],capture_output=True,text=True,timeout=90)
 (case/'reinstall-plan.stdout').write_text(repeated.stdout);(case/'reinstall-plan.stderr').write_text(repeated.stderr)
 if repeated.returncode:raise RuntimeError('Reinstall planning failed: '+repeated.stderr[-1500:])
 repeated_plan=json.loads(repeated.stdout)
 if repeated_plan['blocking']:raise RuntimeError('Reinstall plan blocked: '+str(repeated_plan['blocking']))
 repeated_plan['approved']=True
 code=execute(repeated_plan,case/'reinstall')
 result['cases'].append({'case':'reinstall','exit':code,'report':str(case/'reinstall')})
 if code not in (0,2):raise RuntimeError('Reinstall returned failure '+str(code))
 result['status']='configured-pending-acceptance' if any(c.get('exit')==2 for c in result['cases']) else 'passed'
except Exception as exc:
 result['status']='failed';result['error']=str(exc)
finally:
 (case/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
sys.exit(1 if result['status']=='failed' else 0)
'''


def load_module(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--native-snapshot',type=Path,required=True)
    parser.add_argument('--failure-resume',action='store_true',help='Add a documented one-shot exit after real configuration in the private snapshot, then resume the same reviewed plan')
    args=parser.parse_args(argv)
    rootfs=args.rootfs.resolve();source=args.source.resolve();native=args.native_snapshot.resolve()
    harness=load_module('arch_harness','check_install_arch_clean.py')
    builder=load_module('arch_builder','build_install_arch_native.py')
    harness.container_command(rootfs,source,['true'])
    inputs=json.loads((native/'snapshot-inputs.json').read_text())
    prefixes=('src/niri-taskbar/','src/adws-runtime/','src/adws-start-menu/','src/panel-rows/','vendor/')
    generated_tests={'src/panel-rows/'+name for name in ('test-motion-events','test-panel','test-start-instances','test-vertical')}
    for name,digest in inputs.items():
        if name.startswith(prefixes) or name=='src/niri-desktop-layer/integration/waybar-space.c':
            # These four Makefile test executables were present in an early
            # snapshot; they are build outputs, not inputs to any shipped ELF.
            if name in generated_tests and (native/name).read_bytes().startswith(b'\x7fELF'):continue
            path=source/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise RuntimeError('Native input changed; rebuild before installing: '+name)
    stage=builder.snapshot(source,rootfs.parent/'installer-cases')
    if args.failure_resume:
        script=stage/'scripts/adws-install.sh'
        with script.open('a') as output:
            output.write('\n# Isolated validation fault injection; never part of the product.\n'
                         'if [[ -f "$XDG_STATE_HOME/adws-validation-fail-once" ]]; then\n'
                         '  rm -- "$XDG_STATE_HOME/adws-validation-fail-once"\n'
                         '  exit 23\nfi\n')
        snapshot_inputs=json.loads((stage/'snapshot-inputs.json').read_text())
        snapshot_inputs['scripts/adws-install.sh']=hashlib.sha256(script.read_bytes()).hexdigest()
        (stage/'snapshot-inputs.json').write_text(json.dumps(snapshot_inputs,indent=2)+'\n')
        (stage/'validation-injection.json').write_text(json.dumps({'file':'scripts/adws-install.sh','kind':'one-shot exit 23 after real configuration','scope':'isolated snapshot only'})+'\n')
    shutil.copytree(native/'prebuilt',stage/'prebuilt')
    manifest=json.loads((stage/'prebuilt/manifest.json').read_text())
    for name,digest in manifest['sha256'].items():
        if hashlib.sha256((stage/'prebuilt'/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Invalid native artifact hash: '+name)
    manifest['source_tree_sha256']=hashlib.sha256((stage/'snapshot-inputs.json').read_bytes()).hexdigest()
    (stage/'prebuilt/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    home='/tmp/adws-install-fixtures/'+stage.name+'/home'
    command=harness.container_command(rootfs,stage,['python','-c',CASE])
    mount=command.index(str(stage));assert command[mount-1]=='--ro-bind';command[mount-1]='--bind'
    # Environment is recreated inside bwrap; these paths are all in the rootfs.
    env_index=command.index('HOME=/root');command[env_index]='HOME='+home
    command[env_index:env_index]=['XDG_CONFIG_HOME='+home+'/.config','XDG_DATA_HOME='+home+'/.local/share',
        'XDG_STATE_HOME='+home+'/.local/state','XDG_CACHE_HOME='+home+'/.cache','USER=adws-fixture','LOGNAME=adws-fixture']
    if args.failure_resume:command[env_index:env_index]=['ADWS_VALIDATION_FAILURE_RESUME=1']
    output=stage/'lifecycle.log'
    print('Installer snapshot:',stage,flush=True);print('Fixture HOME:',home,flush=True);print('Log:',output,flush=True)
    with output.open('w') as stream:
        result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
    print('Lifecycle fixture exit:',result.returncode,flush=True)
    return result.returncode


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);raise SystemExit(1)

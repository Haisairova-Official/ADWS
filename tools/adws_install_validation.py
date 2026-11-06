"""Evidence-backed release support matrix; tests never imply physical certification."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=1
CASES={
    'install.fresh':'全新安装', 'install.upgrade':'旧版本升级', 'install.reinstall':'重复安装',
    'install.uninstall':'卸载并保留系统配置', 'install.rollback':'失败回滚',
    'feature.preview':'窗口预览', 'feature.screenshot':'截图', 'feature.clipboard':'剪贴板',
    'feature.launch':'默认应用启动', 'feature.taskbar':'任务栏状态',
    'state.tiled':'平铺窗口', 'state.floating':'浮动窗口', 'state.empty_workspace':'空工作区',
    'state.multi_monitor':'多显示器', 'state.docked':'任务栏吸附', 'state.undocked':'任务栏悬浮',
    'state.theme_switch':'主题/自动配色切换',
}
ENVIRONMENTS=('physical','vm','container','nested')
NESTED={'tray':('tests/check_tray_wayland.py','tray::gui_tests::overflow_dismisses_on_external_wayland_click'),
        'shift':('tests/check_shift_wayland.py','button::action_tests::wayland_layer_shift_menu')}


def digest(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(65536):sha.update(chunk)
    return sha.hexdigest()


def timestamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',prefix='.validation-',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name)
        try:
            json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        except BaseException:temporary.unlink(missing_ok=True);raise
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def record(directory, artifact, case, *, status, origin, environment, distro, niri_version,
           tester, hardware, display_count=1, clean=False, proof=(), notes='', baseline=None):
    """Record actual observation and copy proofs; recording alone never certifies."""
    if case not in CASES and not (origin=='automated' and case in ('nested.tray','nested.shift')):raise ValueError('Unknown matrix case')
    if status not in ('passed','failed','blocked'):raise ValueError('Invalid observation status')
    if origin not in ('manual','automated') or environment not in ENVIRONMENTS:raise ValueError('Invalid evidence origin/environment')
    if not tester.strip() or not notes.strip():raise ValueError('Tester and observations are required')
    if status=='passed' and (not proof or not niri_version.strip() or not hardware.strip()):
        raise ValueError('Passed evidence needs proof files, Niri version and hardware description')
    artifact=Path(artifact)
    if not artifact.is_file():raise ValueError('Select the exact release artifact file that was tested')
    if not isinstance(display_count,int) or display_count<1:raise ValueError('Invalid display count')
    directory=Path(directory);identifier=uuid.uuid4().hex
    folder=directory/identifier;folder.mkdir(parents=True)
    proofs=[]
    try:
        for index,path in enumerate(proof):
            path=Path(path)
            if not path.is_file() or path.is_symlink() or path.stat().st_size>128*1024*1024:
                raise ValueError('Proof must be a regular file at most 128 MiB')
            target=folder/f'proof-{index}{path.suffix}'
            shutil.copy2(path,target)
            proofs.append({'file':target.name,'sha256':digest(target),'bytes':target.stat().st_size})
        value={'schema_version':SCHEMA,'id':identifier,'recorded_at':timestamp(),'case':case,'status':status,
               'origin':origin,'environment':environment,'clean_environment':bool(clean),'distro':distro,
               'niri_version':niri_version,'tester':tester,'hardware':hardware,'display_count':display_count,
               'notes':notes,'artifact':{'name':artifact.name,'sha256':digest(artifact)},'proof':proofs,
               'baseline_artifact_sha256':digest(baseline) if baseline else None}
        path=folder/'evidence.json';write_json(path,value);return path
    except BaseException:
        shutil.rmtree(folder);raise


def proof_errors(path, row):
    errors=[]
    if not isinstance(row.get('proof'),list) or not row['proof']:return ['no attached proof']
    for item in row['proof']:
        if not isinstance(item,dict):errors.append('invalid proof entry');continue
        name=item.get('file','')
        if not isinstance(name,str) or Path(name).name!=name or name in ('','.', '..'):
            errors.append('unsafe proof path');continue
        proof=Path(path).parent/name
        if proof.is_symlink() or not proof.is_file() or digest(proof)!=item.get('sha256'):
            errors.append('missing or changed proof: '+name)
    return errors


def observation_errors(row):
    errors=[]
    if row.get('schema_version')!=SCHEMA:errors.append('unsupported evidence schema')
    if row.get('status') not in ('passed','failed','blocked'):errors.append('invalid status')
    if row.get('origin') not in ('manual','automated') or row.get('environment') not in ENVIRONMENTS:errors.append('invalid evidence origin/environment')
    if row.get('case') not in CASES and row.get('case') not in ('nested.tray','nested.shift'):errors.append('unknown case')
    try:
        stamp=datetime.datetime.fromisoformat(row['recorded_at'])
        if stamp.tzinfo is None:raise ValueError()
    except (KeyError,ValueError,TypeError):errors.append('missing timezone-aware observation date')
    if row.get('status')=='passed':
        for field in ('tester','hardware','notes','niri_version','distro'):
            if not isinstance(row.get(field),str) or not row[field].strip():errors.append('missing observation '+field)
    if not isinstance(row.get('display_count'),int) or row['display_count']<1:errors.append('invalid display count')
    return errors


def review(path, reviewer, notes):
    """A separate explicit human decision, bound to the exact evidence JSON."""
    path=Path(path);row=json.loads(path.read_text())
    if row.get('schema_version')!=SCHEMA or row.get('origin')!='manual' or row.get('status')!='passed':
        raise ValueError('Only manual passed evidence can receive release review')
    if not reviewer.strip() or not notes.strip():raise ValueError('Reviewer and review notes are required')
    errors=observation_errors(row)+proof_errors(path,row)
    if errors:raise ValueError('; '.join(errors))
    value={'schema_version':SCHEMA,'evidence_sha256':digest(path),'reviewed_at':timestamp(),
           'reviewer':reviewer,'notes':notes,'decision':'accepted'}
    destination=path.with_name('review.json');write_json(destination,value);return destination


def check(directory, artifact):
    """Only all reviewed, clean physical Arch cases can grant complete support."""
    expected=digest(artifact);directory=Path(directory)
    records=[];invalid=[]
    for path in sorted(directory.glob('*/evidence.json')):
        try:
            row=json.loads(path.read_text())
            if not isinstance(row,dict) or row.get('schema_version')!=SCHEMA:raise ValueError('unsupported evidence schema')
            if row.get('artifact',{}).get('sha256')!=expected:
                invalid.append({'record':str(path),'reason':'different release artifact'});continue
            errors=observation_errors(row)+(proof_errors(path,row) if row.get('status')=='passed' else [])
            try:decision=json.loads(path.with_name('review.json').read_text())
            except (OSError,ValueError):decision={}
            reviewed=(isinstance(decision,dict) and decision.get('schema_version')==SCHEMA and decision.get('decision')=='accepted'
                      and decision.get('evidence_sha256')==digest(path) and bool(decision.get('reviewer')) and bool(decision.get('notes')))
            if row.get('case')=='state.multi_monitor' and row.get('display_count',0)<2:errors.append('multi-monitor case requires at least two displays')
            if row.get('case') in ('install.upgrade','install.rollback'):
                baseline=row.get('baseline_artifact_sha256')
                if not isinstance(baseline,str) or not re.fullmatch('[0-9a-f]{64}',baseline) or baseline==expected:
                    errors.append('upgrade/rollback must identify the distinct baseline artifact')
            records.append({'record':str(path),'case':row.get('case'),'status':row.get('status'),'origin':row.get('origin'),
                'environment':row.get('environment'),'distro':row.get('distro'),'clean':row.get('clean_environment'),
                'niri_version':row.get('niri_version'),'hardware':row.get('hardware'),'display_count':row.get('display_count'),
                'tester':row.get('tester'),'notes':row.get('notes'),'baseline_artifact_sha256':row.get('baseline_artifact_sha256'),
                'recorded_at':str(row.get('recorded_at','')),'reviewed':reviewed,'errors':errors,
                'evidence_sha256':digest(path),'review_sha256':digest(path.with_name('review.json')) if path.with_name('review.json').is_file() else None,
                'proof_hashes':[item.get('sha256') for item in row.get('proof',[]) if isinstance(item,dict)],
                'eligible':not errors and reviewed and row.get('status')=='passed' and row.get('origin')=='manual'
                    and row.get('environment')=='physical' and row.get('clean_environment') is True and row.get('distro')=='arch'})
        except (OSError,ValueError,AttributeError,TypeError) as error:invalid.append({'record':str(path),'reason':str(error)})
    matrix={}
    for case,title in CASES.items():
        candidates=[row for row in records if row['case']==case]
        # A later failure must invalidate a past green result, never disappear
        # behind an older successful screenshot from the same release.
        candidates.sort(key=lambda row:row['recorded_at'])
        latest=candidates[-1] if candidates else None
        matrix[case]={'title':title,'status':'accepted' if latest and latest['eligible'] else 'pending',
                      'latest':latest}
    complete=all(row['status']=='accepted' for row in matrix.values()) and not any(row['reason']!='different release artifact' for row in invalid)
    return {'schema_version':SCHEMA,'checked_at':timestamp(),'artifact_sha256':expected,
            'support_level':'complete' if complete else 'not-certified','complete_support':complete,
            'matrix':matrix,'supplemental':[row for row in records if row['case'] not in CASES],
            'rejected_records':invalid,'report_digest_basis':'artifact hash + evidence/review/proof hashes',
            'notice':'Manual evidence is a recorded human observation, not an automatic proof of hardware compatibility.'}


def nested_binary(root, name):
    base=Path(root)/'src/niri-taskbar/target/debug'
    candidates=list((base/'deps').glob('niri_taskbar-*'))+list((base/'build/niri-taskbar').glob('*/out/niri_taskbar-*'))
    for binary in sorted(candidates,key=lambda p:p.stat().st_mtime,reverse=True):
        if binary.is_file() and os.access(binary,os.X_OK) and binary.suffix=='':
            listed=subprocess.run([str(binary),'--list'],capture_output=True,text=True,timeout=10)
            if listed.returncode==0 and name+':' in listed.stdout:return binary
    return None


def run_nested(name, directory, artifact, *, root=ROOT, timeout=120):
    """Run existing real-input regressions with a private home, display and bus."""
    if name not in NESTED:raise ValueError('Unknown isolated regression')
    script,test=NESTED[name];root=Path(root)
    missing=[program for program in ('niri','Xvfb','xdotool','dbus-run-session') if not shutil.which(program)]
    binary=nested_binary(root,test) if not missing else None
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    log=directory/('nested-'+name+'-'+uuid.uuid4().hex+'.log')
    if missing or binary is None:
        log.write_text('Missing tools: '+', '.join(missing)+'\n' if missing else 'Build native tests first: cargo test --offline --lib --no-run\n')
        return record(directory,artifact,'nested.'+name,status='blocked',origin='automated',environment='nested',
                      distro='unknown',niri_version='',tester='isolated-runner',hardware='software renderer',proof=[log],notes=log.read_text())
    version=subprocess.run(['niri','--version'],capture_output=True,text=True,timeout=10).stdout.strip()
    provenance=log.with_suffix('.provenance.json')
    source_hashes={str(p.relative_to(root)):digest(p) for p in (root/'src/niri-taskbar/src').rglob('*') if p.is_file()}
    write_json(provenance,{'source_root':str(root.resolve()),'driver_sha256':digest(root/script),'native_test_sha256':digest(binary),
                          'native_source_hashes':source_hashes,'note':'Supplementary source regression; artifact correspondence requires human review.'})
    with tempfile.TemporaryDirectory(prefix='adws-release-validation-') as temporary:
        isolated=Path(temporary);home=isolated/'home';home.mkdir()
        (isolated/'tests').mkdir();shutil.copy2(root/script,isolated/script)
        native=isolated/'src/niri-taskbar/target/debug/deps';native.mkdir(parents=True)
        (native/binary.name).symlink_to(binary.resolve())
        env={key:value for key,value in os.environ.items() if key not in ('DISPLAY','WAYLAND_DISPLAY','NIRI_SOCKET','DBUS_SESSION_BUS_ADDRESS','GDK_BACKEND','HYPRLAND_INSTANCE_SIGNATURE','NIRI_CONFIG') and not key.startswith('ADWS_')}
        runtime=isolated/'runtime';runtime.mkdir(mode=0o700)
        env.update(HOME=str(home),XDG_RUNTIME_DIR=str(runtime),XDG_CONFIG_HOME=str(home/'config'),XDG_DATA_HOME=str(home/'data'),
                   XDG_STATE_HOME=str(home/'state'),XDG_CACHE_HOME=str(home/'cache'),TMPDIR=str(isolated),
                   GIO_USE_VFS='local',NO_AT_BRIDGE='1',LIBGL_ALWAYS_SOFTWARE='1')
        with log.open('w') as output:
            output.write('Actual isolated regression: '+script+'\n');output.flush()
            wrapper="import signal,runpy,sys; signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())); runpy.run_path(sys.argv[1],run_name='__main__')"
            child=subprocess.Popen(['dbus-run-session','--',sys.executable,'-c',wrapper,str(isolated/script)],env=env,cwd=isolated,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # SIGTERM allows the existing script's finally block to run only
                # if it handles the signal; also stop the private process group.
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                code=124;output.write('\nRunner timed out; result is failed.\n')
    try:distro=__import__('platform').freedesktop_os_release().get('ID','unknown')
    except OSError:distro='unknown'
    return record(directory,artifact,'nested.'+name,status='passed' if code==0 else 'failed',origin='automated',environment='nested',
                  distro=distro,niri_version=version,tester='isolated-runner',hardware='Xvfb + software renderer',proof=[log,provenance],
                  notes=f'{script} exited {code}; supplementary regression only, not a clean physical installation test.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--record',choices=tuple(CASES));action.add_argument('--check',action='store_true')
    action.add_argument('--review',type=Path);action.add_argument('--run-nested',choices=tuple(NESTED))
    parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--artifact',type=Path)
    parser.add_argument('--status',choices=('passed','failed','blocked'),default='blocked')
    parser.add_argument('--environment',choices=ENVIRONMENTS,default='container');parser.add_argument('--distro',default='unknown')
    parser.add_argument('--niri-version',default='');parser.add_argument('--tester',default='');parser.add_argument('--reviewer',default='')
    parser.add_argument('--hardware',default='');parser.add_argument('--displays',type=int,default=1)
    parser.add_argument('--clean',action='store_true');parser.add_argument('--proof',action='append',type=Path,default=[])
    parser.add_argument('--notes',default='');parser.add_argument('--baseline',type=Path)
    args=parser.parse_args(argv)
    if args.review:
        print(review(args.review,args.reviewer,args.notes));return 0
    if not args.artifact:parser.error('--artifact is required')
    if args.check:
        report=check(args.directory,args.artifact)
        report['report_sha256']=hashlib.sha256(json.dumps(report,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        destination=args.directory/'support-report.json';write_json(destination,report)
        print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['complete_support'] else 2
    if args.run_nested:
        result=run_nested(args.run_nested,args.directory,args.artifact);print(result)
        return 0 if json.loads(result.read_text())['status']=='passed' else 2
    print(record(args.directory,args.artifact,args.record,status=args.status,origin='manual',environment=args.environment,
                 distro=args.distro,niri_version=args.niri_version,tester=args.tester,hardware=args.hardware,
                 display_count=args.displays,clean=args.clean,proof=args.proof,notes=args.notes,baseline=args.baseline))
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print('Validation incomplete: '+str(error),file=sys.stderr);raise SystemExit(1)

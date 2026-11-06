#!/usr/bin/env python3
"""Repeatable Arch dependency audit in a previously verified bootstrap rootfs.

The caller provisions/verifies the official bootstrap tarball. This harness never
runs a package manager on the host, binds a host session, or runs install.sh.
Dependency installation requires --install-dependencies explicitly. It is not
proof of physical GPU, normal-user login, or systemd PID1 compatibility.
"""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys

AUDIT = r'''
import json,sys,subprocess
from pathlib import Path
sys.path.insert(0,'/opt/adws/tools')
from adws_install_workflow import selected_plan
from adws_setup import PACKAGES
from adws_niri_install import BUILD_PACKAGES, SESSION_PACKAGES
plan=selected_plan('fresh',root=Path('/opt/adws'))
groups={'fresh':plan['package_candidates']+SESSION_PACKAGES+['niri'],
        'native-build':PACKAGES['pacman']['build'],
        'waybar-build':PACKAGES['pacman']['waybar-build'],
        'niri-build':BUILD_PACKAGES['pacman'],
        'isolated-graphics-tests':['xorg-server-xvfb','xorg-xauth','mesa','dbus']}
packages=list(dict.fromkeys(package for names in groups.values() for package in names))
missing={};available={}
for package in packages:
 result=subprocess.run(['pacman','-Si','--',package],capture_output=True,text=True,timeout=30)
 if result.returncode:missing[package]=result.stderr.strip()[:400]
 else:
  fields={line.split(':',1)[0].strip():line.split(':',1)[1].strip() for line in result.stdout.splitlines() if ':' in line}
  available[package]={'version':fields.get('Version'),'repository':fields.get('Repository')}
print(json.dumps({'environment':'Arch bootstrap root-mapped user-space container',
 'groups':groups,'packages':packages,'available':available,'missing':missing,
 'plan_blocking':plan['blocking'],'applications':plan['applications'],
 'system_release':Path('/etc/os-release').read_text()},ensure_ascii=False,indent=2))
'''


NESTED_SMOKE = r"""
import json,os,subprocess,tempfile,time,sys
from pathlib import Path
from PIL import Image
report=Path('/root/adws-validation-nested');report.mkdir(exist_ok=True)
result={'environment':'root-mapped Arch user-space container; software rendered nested X11/Wayland','checks':{}}
children=[]
try:
 with tempfile.TemporaryDirectory(prefix='adws-nested-') as d:
  root=Path(d);runtime=root/'runtime';runtime.mkdir(mode=0o700)
  config=root/'config.kdl';config.write_text('prefer-no-csd\n')
  logs=[]
  def start(argv,env,logname):
   out=(report/logname).open('w');logs.append(out)
   child=subprocess.Popen(argv,env=env,stdout=out,stderr=out);children.append(child);return child
  x=start(['Xvfb',':91','-screen','0','1280x720x24','-nolisten','tcp'],os.environ,'xvfb.log')
  for _ in range(100):
   if Path('/tmp/.X11-unix/X91').exists():break
   if x.poll() is not None:raise RuntimeError('Xvfb exited')
   time.sleep(.05)
  env={**os.environ,'DISPLAY':':91','XDG_RUNTIME_DIR':str(runtime),'LIBGL_ALWAYS_SOFTWARE':'1','GSK_RENDERER':'cairo'}
  niri=start(['niri','--config',str(config)],env,'niri.log')
  socket=None
  for _ in range(300):
   sockets=list(runtime.glob('niri*.sock'));ways=[p for p in runtime.glob('wayland-*') if p.is_socket()]
   if sockets and ways:socket=sockets[0];display=ways[0];break
   if niri.poll() is not None:raise RuntimeError('Niri exited: '+(report/'niri.log').read_text()[-1800:])
   time.sleep(.05)
  if socket is None:raise RuntimeError('Niri IPC did not appear')
  env.update(NIRI_SOCKET=str(socket),WAYLAND_DISPLAY=display.name,GDK_BACKEND='wayland')
  def command(argv):return subprocess.run(argv,env=env,capture_output=True,text=True,timeout=15)
  outputs=command(['niri','msg','--json','outputs']);result['checks']['ipc_outputs']={'exit':outputs.returncode,'data':json.loads(outputs.stdout)}
  app=start(['python','-c',"import gi;gi.require_version('Gtk','3.0');from gi.repository import Gtk,GLib;w=Gtk.Window(title='ADWS isolated fixture');w.set_default_size(400,200);w.add(Gtk.Label(label='Isolated Arch smoke test'));w.show_all();GLib.timeout_add_seconds(30,Gtk.main_quit);Gtk.main()"],env,'gtk.log')
  windows=[]
  for _ in range(100):
   response=command(['niri','msg','--json','windows']);windows=json.loads(response.stdout)
   if any(w.get('title')=='ADWS isolated fixture' for w in windows):break
   time.sleep(.1)
  result['checks']['gtk_window']={'present':any(w.get('title')=='ADWS isolated fixture' for w in windows),'windows':windows}
  screenshot=root/'capture.png'
  shot=command(['grim',str(screenshot)])
  result['checks']['grim_screenshot']={'exit':shot.returncode,'stderr':shot.stderr.strip()}
  if screenshot.exists():
   with Image.open(screenshot) as image:image.load();result['checks']['grim_screenshot']['size']=list(image.size)
  passed=outputs.returncode==0 and result['checks']['gtk_window']['present'] and shot.returncode==0 and 'size' in result['checks']['grim_screenshot']
  result['status']='passed' if passed else 'failed'
except Exception as exc:result['status']='failed';result['error']=str(exc)
finally:
 for child in reversed(children):
  if child.poll() is None:
   child.terminate()
   try:child.wait(timeout=3)
   except subprocess.TimeoutExpired:child.kill();child.wait()
 (report/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2))

sys.exit(0 if result['status']=='passed' else 1)
"""

def container_command(rootfs, source, command):
    rootfs=Path(rootfs).resolve();source=Path(source).resolve()
    if rootfs==Path('/') or not (rootfs/'usr/bin/pacman').is_file():
        raise ValueError('Refusing rootfs: expected an isolated Arch bootstrap tree, never /')
    if not (source/'install.sh').is_file():raise ValueError('Invalid ADWS source directory')
    release=(rootfs/'etc/os-release').read_text()
    if not any(line in ('ID=arch','ID="arch"') for line in release.splitlines()):raise ValueError('Rootfs is not Arch')
    return ['bwrap','--unshare-all','--share-net','--uid','0','--gid','0',
            '--bind',str(rootfs),'/', '--ro-bind',str(source),'/opt/adws',
            '--ro-bind','/etc/resolv.conf','/etc/resolv.conf','--proc','/proc','--dev','/dev','--tmpfs','/run',
            '--chdir','/root','/usr/bin/env','-i','HOME=/root','PATH=/usr/bin','LANG=C.UTF-8',*command]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report-dir',type=Path)
    parser.add_argument('--install-dependencies',action='store_true')
    parser.add_argument('--nested-smoke',action='store_true',help='Run isolated Xvfb/Niri/GTK/screenshot smoke test; does not install ADWS')
    args=parser.parse_args(argv)
    if not shutil.which('bwrap'):raise RuntimeError('bubblewrap is required on the host; harness does not install it')
    report=args.report_dir or args.rootfs.parent/'reports'
    report.mkdir(parents=True,exist_ok=True)
    result=subprocess.run(container_command(args.rootfs,args.source,['python','-c',AUDIT]),capture_output=True,text=True,timeout=300)
    (report/'package-audit.stdout').write_text(result.stdout)
    (report/'package-audit.stderr').write_text(result.stderr)
    if result.returncode:raise RuntimeError('Audit failed inside container; see '+str(report/'package-audit.stderr'))
    audit=json.loads(result.stdout);audit['recorded_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (report/'package-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    print('Packages:',len(audit['packages']),'Missing:',', '.join(audit['missing']) or 'none')
    print('Reports:',report)
    if audit['missing']:return 1
    if args.install_dependencies:
        path=report/'dependency-install.log'
        command=container_command(args.rootfs,args.source,['pacman','-S','--needed','--noconfirm','--',*audit['packages']])
        with path.open('w') as output:
            result=subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,timeout=3600)
        (report/'dependency-install-result.json').write_text(json.dumps({'exit_code':result.returncode,
            'log':str(path),'scope':'isolated rootfs only'},indent=2)+'\n')
        print('Container dependency install exit:',result.returncode,'Log:',path)
        if result.returncode:return result.returncode
    if args.nested_smoke:
        command=container_command(args.rootfs,args.source,['dbus-run-session','--','python','-c',NESTED_SMOKE])
        result=subprocess.run(command,capture_output=True,text=True,timeout=90)
        (report/'nested-smoke.stdout').write_text(result.stdout);(report/'nested-smoke.stderr').write_text(result.stderr)
        evidence=args.rootfs/'root/adws-validation-nested'
        if (evidence/'report.json').exists():
            shutil.copy2(evidence/'report.json',report/'nested-smoke.json')
            for name in ('xvfb.log','niri.log','gtk.log'):
                if (evidence/name).exists():shutil.copy2(evidence/name,report/('nested-'+name))
        print('Nested graphical smoke exit:',result.returncode)
        return result.returncode
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);raise SystemExit(1)

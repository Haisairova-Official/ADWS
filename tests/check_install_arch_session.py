#!/usr/bin/env python3
"""Run the installed ADWS fixture in a private, software-rendered Niri session.

Requires a successful check_install_arch_lifecycle.py snapshot. Only that copy
and the supplied Arch rootfs are writable; no host session or GPU is exposed.
The systemd/PAM/physical-input portions of a real login remain untested.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

SESSION = r'''
import hashlib,json,os,subprocess,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,'/opt/adws/tools')
from adws_install_acceptance import evaluate
report=Path('/opt/adws/session-evidence');report.mkdir(exist_ok=True)
result={'environment':'root-mapped clean Arch; private D-Bus, Xvfb, software Niri; no physical GPU or normal-user login','checks':{}}
children=[];logs=[];session_config=None
def start(argv,env,name,**kwargs):
 log=(report/(name+'.log')).open('w');logs.append(log)
 child=subprocess.Popen(argv,env=env,stdout=log,stderr=log,**kwargs);children.append(child);return child
try:
 with tempfile.TemporaryDirectory(prefix='adws-session-') as folder:
  runtime=Path(folder)/'runtime';runtime.mkdir(mode=0o700)
  xvfb=start(['Xvfb',':92','-screen','0','1280x800x24','-nolisten','tcp'],os.environ,'xvfb')
  for _ in range(100):
   if Path('/tmp/.X11-unix/X92').exists():break
   if xvfb.poll() is not None:raise RuntimeError('Xvfb exited')
   time.sleep(.05)
  env=dict(os.environ,DISPLAY=':92',XDG_RUNTIME_DIR=str(runtime),LIBGL_ALWAYS_SOFTWARE='1',GSK_RENDERER='cairo',XDG_CURRENT_DESKTOP='niri',XDG_SESSION_DESKTOP='niri',XDG_SESSION_TYPE='wayland')
  installed_config=Path(os.environ['XDG_CONFIG_HOME'])/'niri/config.kdl'
  session_config=installed_config.with_name('.adws-validation-session.kdl')
  if session_config.exists():raise RuntimeError('Refusing to overwrite an existing fixture session config')
  installed_text=installed_config.read_text()
  session_config.write_text(installed_text+'\nhotkey-overlay { skip-at-startup; }\n')
  result['session_override']={'hotkey_overlay':'skip-at-startup','installed_config_modified':False}
  result['generated_keybindings']=[line.strip() for line in installed_text.splitlines() if any(key in line for key in ('Mod+Z {','Mod+Alt+Comma {','Mod+Alt+L ', 'Mod+V {'))]
  niri=start(['niri','--config',str(session_config)],env,'niri')
  for _ in range(300):
   sockets=list(runtime.glob('niri*.sock'));displays=[p for p in runtime.glob('wayland-*') if p.is_socket()]
   if sockets and displays:break
   if niri.poll() is not None:raise RuntimeError('Niri exited')
   time.sleep(.05)
  else:raise RuntimeError('Niri IPC did not appear')
  env.update(NIRI_SOCKET=str(sockets[0]),WAYLAND_DISPLAY=displays[0].name,GDK_BACKEND='wayland')
  def command(argv,**kwargs):return subprocess.run(argv,env=env,capture_output=True,text=True,timeout=20,**kwargs)
  command(['dbus-update-activation-environment','DISPLAY','WAYLAND_DISPLAY','XDG_CURRENT_DESKTOP','XDG_RUNTIME_DIR'])
  # Let the real generated spawn-at-startup commands start ADWS themselves.
  for _ in range(100):
   accepted=evaluate(selected=['taskbar'],environ=env)
   if accepted['complete']:break
   if niri.poll() is not None:raise RuntimeError('Niri exited during startup')
   time.sleep(.1)
  result['checks']['taskbar']=accepted
  status=command(['bash','/opt/adws/adws','--status'])
  result['checks']['adws_status']={'exit':status.returncode,'stdout':status.stdout,'stderr':status.stderr}
  manager=command(['busctl','--user','status','org.freedesktop.systemd1'])
  if manager.returncode:
   result['checks']['desktop_service']={'status':'pending','reason':'No systemd user manager in this isolated fixture; real service activation is unverified'}
   desktop=start(['/opt/adws/src/niri-desktop-layer/desktop-layer','--state',str(Path(os.environ['XDG_STATE_HOME'])/'desktop-fixture.json')],env,'desktop-direct')
   for _ in range(50):
    direct=command(['bash','/opt/adws/adws','desktop','--status'])
    if direct.returncode==0 or desktop.poll() is not None:break
    time.sleep(.1)
   result['checks']['desktop_direct_process']={'exit':direct.returncode,'process_exit':desktop.poll(),'scope':'direct rendering process only; does not validate service login'}
  else:
   result['checks']['desktop_service']={'status':'passed' if status.returncode==0 else 'failed'}
  report_app=r"""import gi,json
from pathlib import Path
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme',True)
data=json.loads(Path('/opt/adws/lifecycle-evidence/reinstall/result.json').read_text())
w=Gtk.Window(title='ADWS installed fixture');w.set_default_size(540,440)
box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=22);box.set_border_width(30);w.add(box)
heading=Gtk.Label();heading.set_markup('<span size="22000" weight="bold">ADWS installation</span>');heading.set_xalign(0);box.pack_start(heading,False,False,0)
lines=['Recorded status: '+data['status'],'Completed steps: '+str(len(data['completed'])),'Failed steps: '+str(len(data['failed'])),'Backup records: '+str(len(data['backups'])),'Pending: '+', '.join(data['pending'])]
for text in lines:
 label=Gtk.Label(label=text);label.set_xalign(0);label.set_line_wrap(True);label.set_max_width_chars(48);box.pack_start(label,False,False,0)
box.pack_start(Gtk.Separator(),False,False,0)
note=Gtk.Label(label='Isolated Arch + Niri | Software rendering\nNormal login and physical hardware remain unverified.');note.set_xalign(0);note.set_line_wrap(True);note.set_max_width_chars(48);box.pack_start(note,False,False,0)
w.show_all();GLib.timeout_add_seconds(60,Gtk.main_quit);Gtk.main()
"""
  app=start(['python','-c',report_app],env,'gtk')
  windows=[]
  for _ in range(100):
   response=command(['niri','msg','--json','windows']);windows=json.loads(response.stdout)
   if any(w.get('title')=='ADWS installed fixture' for w in windows):break
   time.sleep(.1)
  result['checks']['gtk_window']={'present':any(w.get('title')=='ADWS installed fixture' for w in windows),'windows':windows}
  sys.path.insert(0,'/opt/adws/src/niri-desktop-layer')
  from desktop_layer.terminal import configured_argv,current
  terminal_argv=configured_argv()
  if not terminal_argv:raise RuntimeError('The installed default terminal could not be resolved by ADWS')
  terminal=start(terminal_argv,env,'default-terminal')
  terminal_window=None
  for _ in range(100):
   response=command(['niri','msg','--json','windows']);windows=json.loads(response.stdout)
   terminal_window=next((window for window in windows if window.get('pid')==terminal.pid),None)
   if terminal_window or terminal.poll() is not None:break
   time.sleep(.1)
  result['checks']['default_terminal']={'desktop_id':current(),'argv':terminal_argv,'window':terminal_window,'process_exit':terminal.poll()}
  # Catch an early post-map crash instead of treating a briefly visible PID as
  # successful startup. This is still a smoke test, not a long-running soak.
  time.sleep(2)
  stable=command(['bash','/opt/adws/adws','--status'])
  result['checks']['stable_processes']={'exit':stable.returncode,'stdout':stable.stdout,'stderr':stable.stderr}
  desktop_owner=command(['gdbus','call','--session','--dest','org.freedesktop.DBus','--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.NameHasOwner','io.github.akizuki.NiriDesktopLayer'])
  result['checks']['desktop_ready']={'exit':desktop_owner.returncode,'owns_bus_name':'true' in desktop_owner.stdout}
  shot=command(['grim',str(report/'installed-session.png')])
  result['checks']['screenshot']={'exit':shot.returncode,'stderr':shot.stderr}
  if shot.returncode==0:
   from PIL import Image
   with Image.open(report/'installed-session.png') as image:
    image.load();result['checks']['screenshot']['size']=list(image.size)
  payload='ADWS isolated clipboard round trip '+hashlib.sha256(os.environ['HOME'].encode()).hexdigest()[:12]
  copied=start(['wl-copy','--foreground','--type','text/plain'],env,'wl-copy',stdin=subprocess.PIPE,text=True)
  copied.stdin.write(payload);copied.stdin.close()
  listing=''
  for _ in range(100):
   history=command(['cliphist','list']);listing=history.stdout
   if payload in listing:break
   time.sleep(.05)
  line=next((line for line in listing.splitlines() if payload in line),None)
  decoded=command(['cliphist','decode'],input=line+'\n') if line else None
  result['checks']['clipboard_history']={'copy_exit':copied.poll(),'history_contains_payload':bool(line),'decode_matches':bool(decoded and decoded.returncode==0 and decoded.stdout==payload)}
  # Automated checks are recorded separately, never fabricated as user-confirmed.
  result['acceptance']=evaluate(exercise=['screenshot'],environ=env)
  desktop_ok=(status.returncode==0 or result['checks'].get('desktop_direct_process',{}).get('exit')==0)
  passed=accepted['complete'] and not result['acceptance']['failed'] and desktop_ok and stable.returncode==0 and result['checks']['desktop_ready']['owns_bus_name'] and result['checks']['gtk_window']['present'] and bool(terminal_window) and shot.returncode==0 and result['checks']['clipboard_history']['decode_matches']
  result['status']='smoke-passed-manual-pending' if passed else 'failed'
except Exception as error:
 result['status']='failed';result['error']=str(error)
finally:
 # A private PID namespace ends all detached child components when bwrap exits.
 for child in reversed(children):
  if child.poll() is None:
   child.terminate()
   try:child.wait(timeout=3)
   except subprocess.TimeoutExpired:child.kill();child.wait()
 for log in logs:log.close()
 if session_config is not None:session_config.unlink(missing_ok=True)
 state=Path(os.environ['XDG_STATE_HOME'])/'adws'
 for name in ('taskbar.log','desktop.log'):
  path=state/name
  if path.is_file():(report/name).write_bytes(path.read_bytes())
 (report/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
sys.exit(0 if result['status']=='smoke-passed-manual-pending' else 1)
'''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs',type=Path,required=True)
    parser.add_argument('--installer-snapshot',type=Path,required=True)
    args=parser.parse_args(argv)
    rootfs=args.rootfs.resolve();stage=args.installer_snapshot.resolve()
    if stage.parent!=rootfs.parent/'installer-cases':raise ValueError('Expected independent installer-cases snapshot')
    result=json.loads((stage/'lifecycle-evidence/result.json').read_text())
    if not any(row.get('case')=='fresh' and row.get('exit') in (0,2) for row in result['cases']):
        raise ValueError('No successful fresh configuration in this fixture')
    home=result['home']
    if not home.startswith('/tmp/adws-install-fixtures/'):raise ValueError('Invalid fixture HOME')
    spec=importlib.util.spec_from_file_location('arch_harness',Path(__file__).with_name('check_install_arch_clean.py'))
    harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)
    cmd=harness.container_command(rootfs,stage,['dbus-run-session','--','python','-c',SESSION])
    # Linux requires CAP_SETFCAP in the parent namespace when a nested loader
    # maps parent UID 0. These capabilities exist only inside this private user
    # namespace; glycin's own sandbox stays enabled, no host privilege is added.
    cmd[1:1]=['--cap-add','CAP_SETUID','--cap-add','CAP_SETGID','--cap-add','CAP_SETFCAP']
    mount=cmd.index(str(stage));assert cmd[mount-1]=='--ro-bind';cmd[mount-1]='--bind'
    index=cmd.index('HOME=/root');cmd[index]='HOME='+home
    cmd[index:index]=['XDG_CONFIG_HOME='+home+'/.config','XDG_DATA_HOME='+home+'/.local/share',
                     'XDG_STATE_HOME='+home+'/.local/state','XDG_CACHE_HOME='+home+'/.cache',
                     'USER=adws-fixture','LOGNAME=adws-fixture']
    with (stage/'session.log').open('w') as output:
        completed=subprocess.run(cmd,stdout=output,stderr=subprocess.STDOUT,timeout=180)
    print('Installed session exit:',completed.returncode,'Report:',stage/'session-evidence/result.json')
    return completed.returncode


if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Exercise real Foot palette configuration and OSC updates in private Niri.

The Arch rootfs and product tree are read-only. Only the supplied evidence
folder is writable on the host; HOME/runtime/X11/Wayland/PIDs are private.
No package manager, physical GPU, host terminal or desktop session is used.
"""
import argparse
import json
from pathlib import Path
import subprocess

QUERY = r'''
import json,os,select,sys,termios,time,tty
from pathlib import Path
folder=Path(sys.argv[1]);folder.mkdir(exist_ok=True)
original=termios.tcgetattr(0);tty.setraw(0)
(folder/'ready.json').write_text(json.dumps({'pid':os.getpid(),'parent':os.getppid(),'term':os.environ.get('TERM'),'watcher':os.environ.get('ADWS_FOOT_PALETTE_PID'),'palette_tty':os.environ.get('ADWS_FOOT_PALETTE_TTY'),'uid':os.getuid(),'tty_owner':os.stat('/dev/tty').st_uid,'stdin_owner':os.fstat(0).st_uid}))
previous=None
try:
 while not (folder/'exit').exists():
  request=(folder/'request').read_text() if (folder/'request').exists() else None
  if request and request!=previous:
   previous=request;os.write(1,b'\x1b]11;?\x1b\\');response=b'';deadline=time.monotonic()+2
   while time.monotonic()<deadline:
    readable,_,_=select.select([0],[],[],.1)
    if readable:
     response+=os.read(0,4096)
     if b'\x1b\\' in response or b'\x07' in response:break
   (folder/(request+'.json')).write_text(json.dumps({'request':request,'response':response.decode('ascii',errors='replace')}))
  time.sleep(.03)
finally:
 termios.tcsetattr(0,termios.TCSANOW,original)
'''

SESSION = r'''
import hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,'/opt/adws/tools')
import adws_palette_sync as palette
report=Path('/root/evidence');children=[];logs=[]
result={'environment':'read-only clean Arch rootfs; private HOME/PID/runtime/DBus/Xvfb/Niri; software rendering; no host terminals','checks':{}}
def wait_until(test,seconds=12,label='condition'):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  value=test()
  if value:return value
  time.sleep(.05)
 raise RuntimeError('Timed out: '+label)
def start(argv,env,name):
 log=(report/(name+'.log')).open('w');logs.append(log)
 child=subprocess.Popen(argv,env=env,stdout=log,stderr=log);children.append(child);return child
def command(argv,env=None,timeout=15):
 return subprocess.run(argv,env=env or os.environ,capture_output=True,text=True,timeout=timeout)
def response(folder,name):
 (folder/'request').write_text(name)
 path=folder/(name+'.json');wait_until(path.exists,label='Foot OSC query '+name)
 raw=json.loads(path.read_text())['response'];match=re.search(r'rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)',raw)
 rgb=('#'+''.join(f'{round(int(value,16)*255/(16**len(value)-1)):02x}' for value in match.groups())) if match else None
 return {'raw':raw,'color':rgb}
def capture(name,env):
 reply=command(['grim',str(report/(name+'.png'))],env)
 return {'exit':reply.returncode,'stderr':reply.stderr}
try:
 home=Path(os.environ['HOME']);config=Path(os.environ['XDG_CONFIG_HOME']);data=Path(os.environ['XDG_DATA_HOME'])
 config.mkdir(parents=True);data.mkdir(parents=True)
 chosen=dict(palette.DEFAULT_PALETTE,surface='#202128')
 proposal=palette.registration_plan(['foot'],config_home=config,data_home=data,home=home,foot_shell='bash',palette=chosen)
 if proposal['conflicts']:raise RuntimeError('Palette registration conflict: '+str(proposal['conflicts']))
 palette.register(proposal,home/'palette-backup')
 generated=config/'foot/foot.ini'
 version=command(['foot','--version']);check=command(['foot','--check-config','--config',str(generated)])
 (report/'foot-version.txt').write_text(version.stdout+version.stderr)
 (report/'foot-config-check.log').write_text(check.stdout+check.stderr)
 (report/'generated-foot.ini').write_text(generated.read_text())
 (report/'generated-foot-colors.ini').write_text((config/'adws/palette/colors.foot.ini').read_text())
 (report/'generated-foot-hook.sh').write_text((config/'adws/palette/foot-hook.sh').read_text())
 result['checks']['config']={'exit':check.returncode,'version':version.stdout.strip() or version.stderr.strip()}
 if check.returncode:
  if os.environ.get('ADWS_FOOT_FIXTURE_ADAPT_SECTION')!='1':raise RuntimeError('Actual Foot rejected generated config')
  # Diagnostic continuation only: change the private generated fixture, never
  # the product source or the rootfs, and record that this is not a product pass.
  original_render=palette.render
  def adapted_render(target,value):
   text=original_render(target,value)
   return text.replace('[colors]','[colors-dark]') if target=='foot' else text
  palette.render=adapted_render
  fragment=config/'adws/palette/colors.foot.ini';fragment.write_text(adapted_render('foot',chosen))
  adapted=command(['foot','--check-config','--config',str(generated)])
  (report/'adapted-config-check.log').write_text(adapted.stdout+adapted.stderr)
  result['fixture_adaptations']=['Replaced [colors] with [colors-dark] only in isolated generated fixture and in-memory renderer']
  result['checks']['adapted_config']={'exit':adapted.returncode}
  hook=config/'adws/palette/foot-hook.sh';hook.write_text(hook.read_text().replace('>/dev/null 2>&1','>>/root/evidence/foot-hook.log 2>&1'))
  if adapted.returncode:raise RuntimeError('Foot rejected diagnostic adapted config')
 runtime=Path(os.environ['XDG_RUNTIME_DIR']);runtime.mkdir(parents=True,mode=0o700,exist_ok=True)
 xvfb=start(['Xvfb',':93','-screen','0','1280x800x24','-nolisten','tcp'],os.environ,'xvfb')
 wait_until(lambda:Path('/tmp/.X11-unix/X93').exists() or xvfb.poll() is not None,label='private Xvfb')
 if xvfb.poll() is not None:raise RuntimeError('Xvfb exited')
 niri_config=config/'niri-test.kdl';niri_config.write_text('prefer-no-csd\nanimations { off; }\nlayout { gaps 8; }\n')
 env=dict(os.environ,DISPLAY=':93',LIBGL_ALWAYS_SOFTWARE='1',GSK_RENDERER='cairo',XDG_CURRENT_DESKTOP='niri',XDG_SESSION_TYPE='wayland')
 niri=start(['niri','--config',str(niri_config)],env,'niri')
 def sockets():
  ways=[p for p in runtime.glob('wayland-*') if p.is_socket()];ipc=list(runtime.glob('niri*.sock'))
  if niri.poll() is not None:raise RuntimeError('Niri exited')
  return (ways[0],ipc[0]) if ways and ipc else None
 wayland,ipc=wait_until(sockets,seconds=20,label='nested Niri')
 env.update(WAYLAND_DISPLAY=wayland.name,NIRI_SOCKET=str(ipc))
 one=report/'terminal-one';one.mkdir(exist_ok=True)
 foot_one=start(['foot','--config',str(generated),'--app-id=adws-foot-palette','--title=ADWS Foot palette one','bash','--noprofile','--rcfile',str(home/'.bashrc'),'-i','-c','python /root/evidence/query-foot.py /root/evidence/terminal-one'],env,'foot-one')
 wait_until(lambda:(one/'ready.json').exists() or foot_one.poll() is not None,label='first real Foot shell')
 if foot_one.poll() is not None:raise RuntimeError('Foot exited before opening query shell')
 palette_path=config/'adws/palette/foot.json'
 watchers=wait_until(lambda:palette.foot_watchers(palette_path),label='first palette watcher')
 before=response(one,'before');result['checks']['first_terminal']={'before':before,'watchers':watchers}
 result['checks']['before_screenshot']=capture('before',env)
 # A second Foot launched from a palette-enabled terminal inherits this exported
 # variable; use that exact inherited value, without inspecting any other TTY.
 two=report/'terminal-two';two.mkdir(exist_ok=True)
 inherited=json.loads((one/'ready.json').read_text())
 env_two=dict(env,ADWS_FOOT_PALETTE_PID=str(watchers[0]),ADWS_FOOT_PALETTE_TTY=inherited.get('palette_tty') or '')
 foot_two=start(['foot','--config',str(generated),'--app-id=adws-foot-palette','--title=ADWS Foot palette two','bash','--noprofile','--rcfile',str(home/'.bashrc'),'-i','-c','python /root/evidence/query-foot.py /root/evidence/terminal-two'],env_two,'foot-two')
 wait_until(lambda:(two/'ready.json').exists() or foot_two.poll() is not None,label='second real Foot shell')
 if foot_two.poll() is not None:raise RuntimeError('Second Foot exited before query shell')
 time.sleep(.4);before_two=response(two,'before')
 next_palette=dict(chosen,surface='#315a72')
 synced=palette.synchronize(next_palette,config_home=config)
 result['checks']['synchronize']=synced
 time.sleep(1.4)
 after=response(one,'after');after_two=response(two,'after')
 result['checks']['first_terminal'].update(after=after,changed=after['color']==next_palette['surface'] and before['color']==chosen['surface'])
 result['checks']['inherited_terminal']={'before':before_two,'after':after_two,'changed':after_two['color']==next_palette['surface'],'watchers':palette.foot_watchers(palette_path),'ready':json.loads((two/'ready.json').read_text())}
 result['checks']['after_screenshot']=capture('after',env)
 from PIL import Image
 pixels={}
 for name,color in [('before',chosen['surface']),('after',next_palette['surface'])]:
  with Image.open(report/(name+'.png')) as image:
   rgb=image.convert('RGB');expected=tuple(bytes.fromhex(color[1:]))
   pixels[name]={'expected':color,'matching_pixels':sum(1 for pixel in rgb.getdata() if pixel==expected),'size':list(rgb.size)}
 result['checks']['rendered_background']=pixels
 owned_watchers=palette.foot_watchers(palette_path)
 for folder in (two,one):(folder/'exit').touch()
 for child in (foot_two,foot_one):
  try:child.wait(timeout=5)
  except subprocess.TimeoutExpired:pass
 time.sleep(1.4)
 active=palette.foot_watchers(palette_path)
 records=list((runtime/'adws/palette-foot').glob('*.json'))
 remaining=[pid for pid in owned_watchers if Path('/proc',str(pid)).exists()]
 result['checks']['cleanup']={'foot_exits':[foot_one.poll(),foot_two.poll()],'active_watchers':active,'owned_pids_still_present':remaining,'remaining_records':[json.loads(path.read_text()) for path in records]}
 result['checks']['same_palette_after_closing']=palette.synchronize(next_palette,config_home=config)
 passed=(check.returncode==0 and result['checks']['first_terminal']['changed'] and result['checks']['inherited_terminal']['changed'] and not active and not remaining and not records and all(row['matching_pixels']>10000 for row in pixels.values()))
 result['status']='passed' if passed else 'failed'
except Exception as error:
 result['status']='failed';result['error']=str(error)
finally:
 for child in reversed(children):
  if child.poll() is None:
   child.terminate()
   try:child.wait(timeout=3)
   except subprocess.TimeoutExpired:child.kill();child.wait()
 for log in logs:log.close()
 (report/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
sys.exit(0 if result['status']=='passed' else 1)
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--adapt-current-foot',action='store_true',help='Diagnostic fixture-only continuation after [colors] rejection; never means the product passed')
    args = parser.parse_args(argv)
    rootfs, source, report = args.rootfs.resolve(), args.source.resolve(), args.report_dir.resolve()
    if rootfs == Path('/') or not (rootfs / 'usr/bin/foot').is_file() or not (rootfs / 'usr/bin/niri').is_file():
        raise ValueError('Expected an isolated rootfs with Foot and Niri already installed')
    if not (source / 'tools/adws_palette_sync.py').is_file():
        raise ValueError('Missing product palette module')
    if report.exists():
        raise ValueError('Choose a new evidence directory; previous results are preserved')
    report.mkdir(parents=True)
    (report / 'query-foot.py').write_text(QUERY)
    command = ['bwrap', '--unshare-all', '--uid', '0', '--gid', '0', '--ro-bind', str(rootfs), '/',
               '--ro-bind', str(source), '/opt/adws',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/run', '--tmpfs', '/root',
               '--dir', '/root/evidence', '--bind', str(report), '/root/evidence',
               '--perms','0700','--dir','/run/foot-palette',
               '--chdir', '/root', '/usr/bin/env', '-i', 'HOME=/root', 'PATH=/usr/bin', 'LANG=C.UTF-8',
               'XDG_CONFIG_HOME=/root/.config', 'XDG_DATA_HOME=/root/.local/share',
               'XDG_STATE_HOME=/root/.local/state', 'XDG_CACHE_HOME=/root/.cache',
               'XDG_RUNTIME_DIR=/run/foot-palette', 'USER=foot-fixture', 'LOGNAME=foot-fixture',
               'ADWS_FOOT_FIXTURE_ADAPT_SECTION='+('1' if args.adapt_current_foot else '0'),
               'dbus-run-session', '--', 'python', '-c', SESSION]
    (report / 'isolation.json').write_text(json.dumps({'rootfs': str(rootfs), 'source': str(source),
        'rootfs_read_only': True, 'private_home_runtime_pid_network': True, 'host_session_exposed': False}, indent=2) + '\n')
    with (report / 'session.log').open('w') as output:
        completed = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=100)
    print('Foot palette exit:', completed.returncode, 'Report:', report / 'result.json')
    return completed.returncode


if __name__ == '__main__':
    raise SystemExit(main())

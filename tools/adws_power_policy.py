"""Per-session ADWS idle policy, delegated only to Wayland/system services."""
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def path():return Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'adws/power-policy.json'


def defaults():
    return {'enabled':False,'ac':{'screen':15,'suspend':0},'battery':{'screen':5,'suspend':20}}


def validate(data):
    if not isinstance(data,dict) or type(data.get('enabled')) is not bool:raise ValueError('Invalid power policy')
    result={'enabled':data['enabled']}
    for source in ('ac','battery'):
        values=data.get(source)
        if not isinstance(values,dict):raise ValueError('Invalid power source')
        result[source]={}
        for field in ('screen','suspend'):
            value=values.get(field)
            if type(value) is not int or not 0<=value<=240:raise ValueError('Invalid idle timeout')
            result[source][field]=value
        if result[source]['suspend'] and result[source]['screen']>result[source]['suspend']:raise ValueError('Screen timeout must precede suspend')
    return result


def load():
    try:return validate(json.loads(path().read_text()))
    except FileNotFoundError:return defaults()


def save(data):
    data=validate(data)
    if data['enabled'] and not shutil.which('swayidle'):raise RuntimeError('swayidle is required for Wayland idle notifications')
    if data['enabled'] and not (os.environ.get('NIRI_SOCKET') or os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')):raise RuntimeError('An active Niri or Hyprland session is required')
    target=path();target.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.power-',dir=target.parent)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,target)
    finally:Path(temp).unlink(missing_ok=True)
    if data['enabled']:launch()
    else:stop_all()


def launch():
    try:
        if not load()['enabled']:return
    except (OSError,ValueError):return
    if not os.environ.get('WAYLAND_DISPLAY'):return
    subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--run'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)


def power_source(root=Path('/sys/class/power_supply')):
    try:
        batteries=[]
        for item in root.iterdir():
            kind=(item/'type').read_text().strip()
            if kind in ('Mains','USB','USB_C') and (item/'online').exists() and (item/'online').read_text().strip()=='1':return 'ac'
            if kind=='Battery':batteries.append((item/'status').read_text().strip())
        return 'battery' if 'Discharging' in batteries else 'ac'
    except OSError:return 'ac'


def idle_args(policy,source):
    values=validate(policy)[source]
    command=[shutil.which('swayidle') or 'swayidle','-w']
    helper=shlex.join([sys.executable,str(Path(__file__).resolve())])
    if values['screen']:
        command+=['timeout',str(values['screen']*60),helper+' --screen-off','resume',helper+' --screen-on']
    if values['suspend']:command+=['timeout',str(values['suspend']*60),helper+' --suspend']
    return command if len(command)>2 else []


def screen(enabled):
    if os.environ.get('NIRI_SOCKET'):
        args=['niri','msg','action','power-on-monitors' if enabled else 'power-off-monitors']
    elif os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):args=['hyprctl','dispatch','dpms','on' if enabled else 'off']
    else:return
    subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,check=True)


def run():
    state=Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'adws'
    state.mkdir(parents=True,exist_ok=True)
    session=os.environ.get('WAYLAND_DISPLAY','default').replace('/','_')
    pidfile=state/('power-policy-'+session+'.json')
    with (state/('power-policy-'+session+'.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        pidfile.write_text(json.dumps({'pid':os.getpid(),'start':process_start(os.getpid())}))
        child=None;previous=None;stopping=False
        def stopped(*_):
            nonlocal stopping
            stopping=True
        signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped)
        try:
            while not stopping:
                try:
                    policy=load()
                    if not policy['enabled']:break
                    source=power_source();current=(json.dumps(policy,sort_keys=True),source)
                    if current!=previous or child is not None and child.poll() is not None:
                        if child is not None:
                            child.terminate()
                            try:child.wait(timeout=3)
                            except subprocess.TimeoutExpired:child.kill();child.wait()
                        screen(True)
                        args=idle_args(policy,source)
                        child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) if args else None
                        previous=current
                except (OSError,ValueError,subprocess.SubprocessError):
                    # Avoid a tight restart loop if the Wayland idle protocol or
                    # compositor command is unavailable.
                    previous=None
                for _ in range(10):
                    if stopping:break
                    time.sleep(.5)
        finally:
            pidfile.unlink(missing_ok=True)
            if child is not None:
                child.terminate()
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            try:screen(True)
            except Exception:pass




def process_start(pid):
    return Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]


def stop_all():
    state=Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'adws'
    for path in state.glob('power-policy-*.json'):
        try:
            data=json.loads(path.read_text());pid=data['pid']
            if type(pid) is not int or pid<=1 or Path('/proc',str(pid)).stat().st_uid!=os.getuid():continue
            argv=Path('/proc',str(pid),'cmdline').read_bytes().split(b'\0')
            helper=str(Path(__file__).resolve()).encode()
            if data.get('start')!=process_start(pid) or helper not in argv or b'--run' not in argv:continue
            os.kill(pid,signal.SIGTERM)
            deadline=time.monotonic()+5
            while path.exists() and time.monotonic()<deadline:time.sleep(.1)
            if path.exists():raise RuntimeError('Idle policy did not stop')
        except (FileNotFoundError,ProcessLookupError):path.unlink(missing_ok=True)


def logind_snapshot():
    from adws_native_services import properties
    current=properties('org.freedesktop.login1','/org/freedesktop/login1','org.freedesktop.login1.Manager')
    fields={'HandlePowerKey':'poweroff','HandleLidSwitch':'suspend','HandleLidSwitchExternalPower':'suspend','HandleLidSwitchDocked':'ignore'}
    result={key:current.get(key,default) for key,default in fields.items()}
    from adws_privileged_settings import TARGET,HEADER
    if TARGET.is_file():
        content=TARGET.read_text()
        if content.startswith(HEADER):
            for line in content.splitlines():
                key,_,value=line.partition('=')
                if key in fields:result[key]=value
    return result


def logind_save(data):
    from adws_privileged_settings import validate
    validate(data)
    logind_write(data)


def logind_write(data):
    helper=str(Path(__file__).with_name('adws_privileged_settings.py').resolve())
    # The fixed helper accepts only an allowlist over stdin. It deliberately
    # does not restart logind: that can terminate the active desktop session.
    result=subprocess.run(['pkexec',sys.executable,'-I',helper],input=json.dumps(data),text=True,capture_output=True,timeout=180)
    if result.returncode:raise RuntimeError(result.stderr.strip() or 'Power policy was not saved')


if __name__=='__main__':
    if sys.argv[1:]==['--run']:run()
    elif sys.argv[1:]==['--screen-off']:screen(False)
    elif sys.argv[1:]==['--screen-on']:screen(True)
    elif sys.argv[1:]==['--suspend']:
        subprocess.run(['systemctl','suspend'],stdin=subprocess.DEVNULL,check=True,timeout=30)
    else:raise SystemExit('Unsupported power action')

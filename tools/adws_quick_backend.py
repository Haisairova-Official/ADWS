"""Bounded, GTK-free taskbar audio and per-output brightness adapters."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from adws_i18n import tr
from adws_system_pages import command, audio_snapshot, audio_change


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid control value')
    return float(value)


def audio(mixer=False):
    data = audio_snapshot()
    from adws_audio_values import usable_device, volume_percent
    data['sinks'] = [d for d in data.get('sinks', []) if usable_device(d)]
    if mixer and shutil.which('pactl'):
        raw = json.loads(command(['pactl', '-f', 'json', 'list', 'sink-inputs']))
        data['apps'] = [{**item, 'volume': volume_percent(item)} for item in raw]
    else: data['apps'] = []
    return data


def audio_write(kind, index, action, value):
    if kind == 'sink': audio_change(kind, index, action, value)
    elif kind == 'sink-input':
        from adws_native_services import audio_set
        audio_set(kind, index, action, value)
    else: raise ValueError('Invalid audio device')


def cache_root():
    root = Path(os.environ.get('XDG_CACHE_HOME') or Path.home()/'.cache')/'adws/quick-controls'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def write_json(path, data):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.'+path.name)
    try:
        with os.fdopen(fd, 'w') as stream: json.dump(data, stream)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def read_json(path, default=None):
    try:
        if path.stat().st_size > 1024*1024: return default
        return json.loads(path.read_text())
    except (OSError, ValueError): return default


def parse_ddc(text):
    """Detect --terse identifies the DRM connector, not an assumed display number."""
    displays, current = [], None
    for line in text.splitlines():
        if match := re.match(r'^Display\s+(\d+)\s*$', line):
            current = {'display': int(match[1])}; displays.append(current)
        elif current is not None:
            if match := re.search(r'DRM connector:\s*(?:card\d+-)?([A-Za-z0-9_.-]+)', line): current['output'] = match[1]
    return {item['output']:item['display'] for item in displays if item.get('output')}


def parse_ddc_buses(text):
    result, bus = {}, None
    for line in text.splitlines():
        if re.match(r'^Display\s+\d+',line): bus=None
        elif match:=re.search(r'I2C bus:\s*/dev/i2c-(\d+)',line): bus=int(match[1])
        elif match:=re.search(r'DRM connector:\s*(?:card\d+-)?([A-Za-z0-9_.-]+)',line):
            if bus is not None:result[match[1]]=bus
    return result


def ddc_args(device):
    if isinstance(device,dict) and type(device.get('bus')) is int and device['bus']>=0:
        return ['--bus',str(device['bus'])]
    index=device.get('display') if isinstance(device,dict) else device
    if type(index) is not int or index<1:raise ValueError('Invalid DDC device')
    return ['--display',str(index)]


def ddc_devices(force=False):
    path = cache_root()/'ddc.json'
    cached = read_json(path, {})
    if not force and time.time()-cached.get('time', 0)<60: return cached.get('devices', {})
    devices = {}
    if shutil.which('ddcutil'):
        try:
            raw = command(['ddcutil','detect','--terse'], timeout=8)
            devices = parse_ddc(raw)
            buses = parse_ddc_buses(raw)
            devices = {name:{'display':index, 'bus':buses.get(name)} for name,index in devices.items()}
        except (OSError, RuntimeError, subprocess.SubprocessError): pass
    write_json(path, {'time':time.time(),'devices':devices})
    return devices


def gamma_call(path, method, args, interface='org.freedesktop.DBus.Properties'):
    from gi.repository import Gio
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return bus.call_sync('rs.wl-gammarelay', path, interface, method, args, None,
                         Gio.DBusCallFlags.NO_AUTO_START, 1200, None)


def gamma_state(output):
    from gi.repository import GLib
    path = '/outputs/'+re.sub('[^A-Za-z0-9_]', '_', output)
    try:
        props = gamma_call(path,'GetAll',GLib.Variant('(s)',('rs.wl.gammarelay',))).unpack()[0]
        return {'path':path, 'temperature':int(props['Temperature']), 'brightness':float(props['Brightness'])*100}
    except (GLib.Error, KeyError, TypeError, ValueError): return None


def night_path(output):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', output): raise ValueError('Invalid output')
    return cache_root()/('night-'+output+'.json')


def owned_night(record, output):
    """A reused PID must never terminate an unrelated application."""
    try:
        pid = int(record['pid'])
        args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return Path(os.fsdecode(args[0])).name == 'wlsunset' and b'-o' in args and output.encode() in args and str(Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]) == record['start']
    except (OSError, KeyError, ValueError, IndexError): return False


def brightness(force=False):
    from adws_display import detect_session, outputs
    session = detect_session()
    try: displays = outputs(session) if session else []
    except (ValueError, OSError, subprocess.SubprocessError): displays = []
    ddcs = ddc_devices(force)
    backlights = list(Path('/sys/class/backlight').glob('*'))
    def inspect(output):
        name = output['name']; gamma = gamma_state(name)
        entry = {'name':name,'description':output.get('description') or name, 'provider':None, 'value':None,
                 'temperature':6500, 'night':False, 'color_provider':None}
        if gamma:
            entry.update(color_provider='gamma',temperature=gamma['temperature'], night=gamma['temperature']<6400, gamma_path=gamma['path'])
        elif shutil.which('wlsunset'):
            record = read_json(night_path(name), {})
            active = owned_night(record, name)
            entry.update(color_provider='wlsunset',temperature=record.get('temperature',4500) if active else 6500,night=active)
        try:
            if name in ddcs:
                raw = command(['ddcutil',*ddc_args(ddcs[name]),'getvcp','10','--terse'], timeout=4)
                match = re.search(r'VCP\s+10\s+C\s+(\d+)\s+(\d+)',raw)
                if not match or int(match[2])<=0: raise ValueError('No brightness response')
                entry.update(provider='ddc',device=ddcs[name], maximum=int(match[2]),value=round(int(match[1])/int(match[2])*100))
            elif name.startswith(('eDP','LVDS','DSI')) and len(backlights)==1 and shutil.which('brightnessctl'):
                device = backlights[0]
                maximum = int((device/'max_brightness').read_text()); value=int((device/'brightness').read_text())
                entry.update(provider='backlight',device=device.name,value=value/maximum*100)
            elif gamma:
                entry.update(provider='gamma',value=gamma['brightness'])
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
            if gamma: entry.update(provider='gamma',value=gamma['brightness'])
        return entry
    with ThreadPoolExecutor(max_workers=3) as pool: return list(pool.map(inspect, displays))


def brightness_write(entry, action, value):
    # Revalidate all device identifiers crossing the UI/backend boundary.
    output = entry['name']; path=night_path(output)
    if action=='brightness':
        value=number(value, 5, 100); provider=entry.get('provider')
        if provider=='ddc':
            device=entry['device']; maximum=entry['maximum']
            args=ddc_args(device)
            if type(maximum) is not int or not 1<=maximum<=65535: raise ValueError('Invalid DDC device')
            command(['ddcutil',*args,'setvcp','10',str(round(value*maximum/100))],timeout=5)
        elif provider=='backlight':
            device=entry['device']
            if not re.fullmatch('[A-Za-z0-9_.-]+',device): raise ValueError('Invalid backlight device')
            command(['brightnessctl','--device',device,'set',f'{round(value)}%'])
        elif provider=='gamma':
            from gi.repository import GLib
            gamma_call('/outputs/'+re.sub('[^A-Za-z0-9_]','_',output),'Set',GLib.Variant('(ssv)',('rs.wl.gammarelay','Brightness',GLib.Variant('d',value/100))))
        else: raise RuntimeError(tr('无可用配置'))
        return
    if action not in ('temperature','night'): raise ValueError('Invalid brightness action')
    temperature=int(number(value, 1000, 10000)) if action=='temperature' else (4500 if value is True else 6500)
    if action=='night' and type(value) is not bool: raise ValueError('Invalid night mode')
    if entry.get('color_provider')=='gamma':
        from gi.repository import GLib
        gamma_call('/outputs/'+re.sub('[^A-Za-z0-9_]','_',output),'Set',GLib.Variant('(ssv)',('rs.wl.gammarelay','Temperature',GLib.Variant('q',temperature))))
    elif entry.get('color_provider')=='wlsunset':
        record=read_json(path,{})
        if owned_night(record,output):
            os.kill(int(record['pid']),signal.SIGTERM)
            for _ in range(20):
                if not owned_night(record,output): break
                time.sleep(.025)
        if action=='night' and value is False:
            path.unlink(missing_ok=True); return
        binary=shutil.which('wlsunset')
        if not binary: raise RuntimeError(tr('无可用配置'))
        process=subprocess.Popen([binary,'-o',output,'-t',str(max(1000,temperature-1)),'-T',str(max(1001,temperature)),'-S','00:00','-s','23:59','-d','0'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        time.sleep(.06)
        if process.poll() is not None: raise RuntimeError(tr('当前屏幕不支持色温调节，或已由其他程序管理。'))
        start=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
        write_json(path,{'pid':process.pid,'start':start,'temperature':temperature})
    else: raise RuntimeError(tr('需要 wl-gammarelay-rs 或 wlsunset 才能调节色温。'))


def step(kind, delta, output=None):
    delta=number(delta,-100,100)
    import fcntl
    with (cache_root()/('step-'+kind+'.lock')).open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if kind=='sound':
            data=audio(); item=next((d for d in data['sinks'] if d.get('default')),None)
            if item: audio_write('sink',item['index'],'volume',min(100,max(0,item['volume']+delta)))
        elif kind=='brightness':
            items=brightness(); item=next((d for d in items if d['name']==output),None) if output else next((d for d in items if d.get('provider')),None)
            if item and item.get('provider'): brightness_write(item,'brightness',min(100,max(5,item['value']+delta)))
        else: raise ValueError('Invalid control kind')

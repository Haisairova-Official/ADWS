"""Optional login/boot appearance: inspect first, preserve by default.

No display-manager switch, service restart, EFI default change or GRUB rewrite
is permitted. Automatic Plymouth rebuilding is restricted to inspected classic
mkinitcpio presets; UKI/signing/custom pipelines require separate manual review.
"""
from __future__ import annotations
import argparse
import configparser
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import uuid

SCHEMA = 1
MARKER = '# ADWS optional login theme'
SDDM_FRAGMENT = '/etc/sddm.conf.d/99-adws-theme.conf'
ALLOWED_CONFIG = {SDDM_FRAGMENT, '/etc/plymouth/plymouthd.conf'}
BACKUP_ROOT = Path('/var/lib/adws/boot-theme-backups')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}')
SYSTEM_ENV = {'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','LANG':'C','LANGUAGE':'','TERM':'dumb'}


def owned_sddm_fragment(content):
    return bool(re.fullmatch(re.escape(MARKER)+r'\n\[Theme\]\nCurrent='+NAME.pattern+r'\n',content))


class _WritersRunning(RuntimeError):
    def __init__(self,writers):
        super().__init__('Rebuild writers could not be stopped; private output and backups retained')
        self.writers=writers


@contextmanager
def _defer_cancellation():
    """Finish recording a just-forked child before cancellation can unwind.

    Temporary Python handlers, rather than a blocked signal mask, ensure exec'd
    children retain their normal signal delivery.
    """
    pending=[]
    def defer(signum,frame):pending.append((signum,frame))
    previous={sig:signal.signal(sig,defer) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:yield
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
        for sig,frame in pending:
            handler=previous[sig]
            if handler==signal.SIG_IGN:continue
            if callable(handler):handler(sig,frame)
            else:raise KeyboardInterrupt('System theme operation cancelled')


@contextmanager
def _ignore_cancellation():
    previous={sig:signal.signal(sig,signal.SIG_IGN) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:yield
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


@contextmanager
def _cancellation_signals():
    def cancelled(_signal,_frame):
        for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,signal.SIG_IGN)
        raise KeyboardInterrupt('System theme operation cancelled')
    previous={sig:signal.signal(sig,cancelled) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:yield
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


def _process_table():
    rows={}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields=path.read_text().rsplit(')',1)[1].split()
            rows[int(path.parent.name)]={'state':fields[0],'parent':int(fields[1]),'start':fields[19]}
        except (OSError,ValueError,IndexError):continue
    return rows


def _signal_process(pid,start,sig):
    """A pidfd pins process identity across PID reuse; never kill by old PGID."""
    try:fd=os.pidfd_open(pid)
    except ProcessLookupError:return
    try:
        row=_process_table().get(pid)
        if row and row['start']==start:
            try:signal.pidfd_send_signal(fd,sig)
            except ProcessLookupError:pass
    finally:os.close(fd)


def _run_rebuild(command,*,check=True,timeout=600,env=None):
    """Own and reap the complete rebuild tree, including detached grandchildren.

    A dedicated privileged helper is single-threaded. Becoming a temporary
    Linux subreaper keeps orphaned build children attributable to this command;
    existing children are excluded. No rollback starts while a writer is alive.
    """
    if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
        raise RuntimeError('Kernel/Python cannot safely signal rebuild descendants')
    probe=os.pidfd_open(os.getpid())
    try:signal.pidfd_send_signal(probe,0)
    finally:os.close(probe)
    libc=ctypes.CDLL(None,use_errno=True);old=ctypes.c_int()
    if libc.prctl(37,ctypes.byref(old),0,0,0)!=0 or libc.prctl(36,1,0,0,0)!=0:
        raise RuntimeError('Cannot safely supervise initramfs rebuild descendants')
    baseline={pid for pid,row in _process_table().items() if row['parent']==os.getpid()}
    child=None;known={}
    def live():
        rows=_process_table();changed=True
        while changed:
            changed=False
            for pid,row in rows.items():
                if pid in baseline or pid==os.getpid():continue
                parent=rows.get(row['parent'])
                adopted=row['parent']==os.getpid() and pid not in baseline
                descended=row['parent'] in known and parent and known[row['parent']]==parent['start']
                if (adopted or descended) and known.get(pid)!=row['start']:
                    known[pid]=row['start'];changed=True
        active={pid for pid,start in known.items() if pid in rows and rows[pid]['start']==start and rows[pid]['state']!='Z'}
        for pid in known:
            if child and pid!=child.pid:
                try:os.waitpid(pid,os.WNOHANG)
                except ChildProcessError:pass
        return active
    def stop():
        if child is None:return
        with _ignore_cancellation():
            for sig,grace in ((signal.SIGTERM,2),(signal.SIGKILL,5)):
                deadline=time.monotonic()+grace
                while True:
                    active=live()
                    if not active:
                        time.sleep(.03);active=live()
                        if not active:break
                    for pid in active:
                        try:_signal_process(pid,known[pid],sig)
                        except OSError:pass  # Remains live; escalation or explicit recovery-blocked follows.
                    if time.monotonic()>=deadline:break
                    time.sleep(.03)
                if not live():break
            if live():raise _WritersRunning({str(pid):known[pid] for pid in live()})
            child.wait()
    try:
        with _defer_cancellation():
            child=subprocess.Popen(command,env=env,start_new_session=True)
            row=_process_table().get(child.pid)
            if row:known[child.pid]=row['start']
        deadline=time.monotonic()+timeout
        while child.poll() is None:
            live()
            if time.monotonic()>=deadline:raise subprocess.TimeoutExpired(command,timeout)
            time.sleep(.03)
        time.sleep(.03)
        if live():raise RuntimeError('Rebuild exited with live background writers')
        if check and child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
        return subprocess.CompletedProcess(command,child.returncode)
    except BaseException:
        stop();raise
    finally:
        libc.prctl(36,old.value,0,0,0)


def _system(root, absolute, no_links=True):
    path=PurePosixPath(absolute)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('Invalid system path')
    result=Path(root)
    for part in path.parts[1:]:
        result=result/part
        if no_links and result.is_symlink():raise ValueError('Symlink system path requires manual review: '+absolute)
    return result


def _read(root,path,limit=1024*1024):
    actual=_system(root,path)
    if not actual.exists():return ''
    if actual.stat().st_size>limit:raise ValueError('Configuration exceeds size limit: '+path)
    return actual.read_text()


def _state(path):
    if path.is_symlink():raise ValueError('Cannot snapshot a symlink: '+str(path))
    if not path.exists():return None
    if not path.is_file():raise ValueError('Not a regular file: '+str(path))
    digest=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):digest.update(chunk)
    return {'sha256':digest.hexdigest(),'size':path.stat().st_size,'mode':path.stat().st_mode & 0o777}


def pe_sections(path):
    """Inspect PE section names without executing/rewriting an EFI executable."""
    with Path(path).open('rb') as stream:
        header=stream.read(64)
        if len(header)!=64 or header[:2]!=b'MZ':return []
        offset=struct.unpack_from('<I',header,60)[0]
        if offset>1024*1024:raise ValueError('Invalid PE header offset')
        stream.seek(offset);coff=stream.read(24)
        if len(coff)!=24 or coff[:4]!=b'PE\0\0':return []
        count=struct.unpack_from('<H',coff,6)[0];optional=struct.unpack_from('<H',coff,20)[0]
        if count>96:raise ValueError('Invalid PE section count')
        stream.seek(optional,1);table=stream.read(count*40)
        if len(table)!=count*40:raise ValueError('Truncated PE section table')
        return [table[i*40:i*40+8].rstrip(b'\0').decode('ascii',errors='replace') for i in range(count)]


def _ini(text):
    config=configparser.ConfigParser(interpolation=None,strict=False);config.optionxform=str
    if text:config.read_string(text)
    return config


def _set_ini(text,section,key,value):
    """Edit one selected key while preserving comments and unrelated settings."""
    parsed=_ini(text)
    lines=text.splitlines(keepends=True);output=[];inside=False;written=False;seen_section=False
    for line in lines:
        heading=re.match(r'\s*\[([^]]+)\]',line)
        if heading:
            if inside and not written:output.append(f'{key}={value}\n');written=True
            inside=heading[1]==section;seen_section|=inside
        if inside and re.match(r'\s*'+re.escape(key)+r'\s*=',line):
            if not written:output.append(f'{key}={value}\n');written=True
        else:output.append(line if line.endswith('\n') else line+'\n')
    if inside and not written:output.append(f'{key}={value}\n');written=True
    if not seen_section:output.append(f'\n[{section}]\n{key}={value}\n')
    result=''.join(output)
    if _ini(result).get(section,key)!=value:raise ValueError('Theme config merge failed')
    return result


def _literal(value, *, array=False):
    """Parse the small literal shell subset; never source arbitrary preset code."""
    if array:
        if not (value.startswith('(') and value.endswith(')')):
            raise ValueError('Expected a literal preset array')
        value=value[1:-1]
    lexer=shlex.shlex(value,posix=True,punctuation_chars=';&|()<>' )
    lexer.whitespace_split=True
    tokens=list(lexer)
    # Reject shell expansion/operators even when quoted. Conservative by design.
    if any(re.search(r'[$`\\;|&<>(){}!*?\n\r]',token) for token in tokens):
        raise ValueError('Dynamic preset syntax requires manual review')
    if not array and len(tokens)>1:raise ValueError('Expected one literal preset value')
    return tokens if array else tokens[0] if tokens else ''


def _static_presets(root):
    outputs=[];presets=[];errors=[];evidence=[];inputs=[]
    directory=_system(root,'/etc/mkinitcpio.d')
    for actual in sorted(directory.glob('*.preset')):
        relative='/'+actual.relative_to(root).as_posix();values={};bad=False
        try:
            for line in _read(root,relative).splitlines():
                line=line.strip()
                if not line or line.startswith('#'):continue
                match=re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)=(.*)',line)
                if not match:raise ValueError('Nonliteral assignment')
                key,value=match.groups()
                if key in values:raise ValueError('Duplicate preset assignment')
                values[key]=_literal(value,array=key=='PRESETS')
        except (ValueError,OSError) as exc:
            errors.append('Dynamic/invalid preset requires manual review: '+relative+': '+str(exc));continue
        configured=values.get('PRESETS')
        if not isinstance(configured,list) or not configured:
            errors.append('Missing static PRESETS: '+relative);continue
        allowed={'PRESETS','ALL_config','ALL_kver'}
        allowed.update(name+'_'+field for name in configured for field in ('image','uki','config','kver','options'))
        if set(values)-allowed:errors.append('Unknown preset variables require manual review: '+relative)
        for key,value in values.items():
            if key.endswith('_config') and value not in ('','/etc/mkinitcpio.conf'):
                errors.append('Custom mkinitcpio configuration: '+relative)
            if key.endswith('_kver'):
                if value.startswith('/boot/') and not re.search(r'[\s]',value):
                    try:
                        path=_system(root,value)
                        if not path.is_file():raise ValueError('Kernel input missing')
                        inputs.append(value)
                    except (ValueError,OSError) as exc:errors.append(str(exc)+': '+relative)
                else:errors.append('Nonstandard kernel source requires manual review: '+relative)
        if not any(key.endswith('_kver') for key in values):errors.append('Missing explicit kernel input: '+relative)
        for name in configured:
            if not NAME.fullmatch(name):errors.append('Invalid preset name: '+relative);continue
            options=values.get(name+'_options','')
            if values.get(name+'_uki') or '--splash' in options or '--uki' in options:
                evidence.append(relative);errors.append('UKI/static splash preset: '+relative);continue
            if options not in ('','-S autodetect','--skiphooks autodetect'):
                errors.append('Custom preset options require manual review: '+relative)
            image=values.get(name+'_image')
            if not isinstance(image,str) or not image.startswith('/boot/') or not image.endswith('.img'):
                errors.append('Unknown initramfs output: '+relative+':'+name);continue
            try:_system(root,image)
            except ValueError as exc:errors.append(str(exc));continue
            if image in outputs:errors.append('Duplicate initramfs output: '+image)
            outputs.append(image)
        presets.append(relative)
    return {'presets':presets,'outputs':outputs,'errors':errors,'uki_evidence':evidence,'inputs':sorted(set(inputs))}


def _safe_glob(root,directory,pattern,warnings):
    try:
        parent=_system(root,directory)
        found=[]
        for path in sorted(parent.glob(pattern)):
            _system(root,'/'+path.relative_to(root).as_posix())
            found.append(path)
        return found
    except (ValueError,OSError) as exc:
        warnings.append(str(exc));return []


def detect(root=Path('/'),runner=subprocess.run,*,login_only=False):
    from adws_login_manager import detect as detect_login
    root=Path(root).resolve();warnings=[]
    def readonly_run(argv,**kwargs):
        if argv[0] not in ('systemctl','bootctl'):raise ValueError('Unexpected read-only system command')
        kwargs['env']=dict(SYSTEM_ENV)
        return runner(['/usr/bin/'+argv[0],*argv[1:]],**kwargs)
    try:login=detect_login(root,readonly_run)
    except (ValueError,OSError,configparser.Error) as exc:
        login={'id':None,'name':'unknown','active':None,'configured':None,'warning':str(exc)};warnings.append(str(exc))
    result={'schema_version':SCHEMA,'root':str(root),'login_manager':{k:v for k,v in login.items() if k!='session_dirs'},
            'bootloader':{'active':'unknown','candidates':[],'evidence':[]},
            'sddm':{'themes':[],'current':'','theme_dir':'/usr/share/sddm/themes','shadowing_current':None},
            'plymouth':{'themes':[],'current':'','installed':False,'hook':False,'splash_enabled':False},
            'uki':{'images':[],'static_splash':[],'configuration':[]},'warnings':warnings,'inputs':[]}
    def read(path):
        try:
            text=_read(root,path)
            result['inputs'].append(path)
            return text
        except (ValueError,OSError,UnicodeError) as exc:warnings.append(str(exc));return ''
    def ini(path):
        try:return _ini(read(path))
        except configparser.Error as exc:warnings.append(str(exc)+': '+path);return _ini('')
    def relative(path):return '/'+path.relative_to(root).as_posix()
    paths=[]
    for directory in ('/usr/lib/sddm/sddm.conf.d','/usr/local/lib/sddm/sddm.conf.d','/etc/sddm.conf.d'):
        paths += [relative(path) for path in _safe_glob(root,directory,'*.conf',warnings)]
    paths.append('/etc/sddm.conf');sddm=_ini('')
    for path in paths:
        cfg=ini(path)
        for section in cfg.sections():
            if not sddm.has_section(section):sddm.add_section(section)
            for key,value in cfg.items(section):sddm.set(section,key,value)
    theme_dir=sddm.get('Theme','ThemeDir',fallback='/usr/share/sddm/themes')
    result['sddm'].update(current=sddm.get('Theme','Current',fallback=''),theme_dir=theme_dir,
        shadowing_current=ini('/etc/sddm.conf').get('Theme','Current',fallback=None))
    try:
        themes_root = _system(root, theme_dir)
        folders = sorted(themes_root.iterdir()) if themes_root.is_dir() else []
    except (ValueError, OSError) as exc:
        warnings.append(str(exc))
        folders = []
    for folder in folders:
        if not folder.is_dir() or not NAME.fullmatch(folder.name):continue
        try:
            if folder.is_symlink() or not (folder/'metadata.desktop').is_file():continue
            meta = _ini(_read(root,relative(folder/'metadata.desktop')))
            main = Path(meta.get('SddmGreeterTheme','MainScript',fallback='Main.qml'))
            if main.is_absolute() or '..' in main.parts:continue
            if _system(root,relative(folder/main)).is_file():result['sddm']['themes'].append(folder.name)
        except (ValueError, OSError, UnicodeError, configparser.Error):
            continue
    for path in paths:
        if path.startswith('/etc/sddm.conf.d/') and Path(path).name>'99-adws-theme.conf' and ini(path).has_option('Theme','Current'):
            result['sddm'].setdefault('later_overrides',[]).append(path)
    if login_only:
        return result
    plymouth=result['plymouth'];plymouth['installed']=bool((root/'usr/bin/plymouth').exists() or (root/'usr/sbin/plymouthd').exists())
    plymouth['current']=ini('/etc/plymouth/plymouthd.conf').get('Daemon','Theme',fallback='')
    plymouth['theme_modules']={}
    for definition in _safe_glob(root,'/usr/share/plymouth/themes','*/*.plymouth',warnings):
        if definition.name!=definition.parent.name+'.plymouth' or not NAME.fullmatch(definition.parent.name):continue
        cfg=ini(relative(definition));module=cfg.get('Plymouth Theme','ModuleName',fallback='')
        if not NAME.fullmatch(module):continue
        candidates=[root/'usr/lib/plymouth'/f'{module}.so',*_safe_glob(root,'/usr/lib',f'*-linux-gnu/plymouth/{module}.so',warnings)]
        for candidate in candidates:
            if candidate.is_file():
                try:_system(root,relative(candidate))
                except ValueError as exc:warnings.append(str(exc));continue
                plymouth['themes'].append(definition.parent.name);plymouth['theme_modules'][definition.parent.name]=relative(candidate);break
    configs=['/etc/mkinitcpio.conf',*[relative(path) for path in _safe_glob(root,'/etc/mkinitcpio.conf.d','*.conf',warnings)]]
    hooks=[]
    for path in configs:
        text='\n'.join(line for line in read(path).splitlines() if not line.strip().startswith('#'))
        found=re.findall(r'(?ms)^\s*HOOKS=\((.*?)\)',text)
        if found:
            try:hooks=_literal('('+found[-1]+')',array=True)
            except ValueError as exc:warnings.append('Cannot parse mkinitcpio HOOKS: '+str(exc))
        if re.search(r'(?m)^\s*(?:source\s|\.\s|HOOKS\+=)',text):warnings.append('Dynamic mkinitcpio hook configuration requires manual review: '+path)
    plymouth['hook']='plymouth' in hooks
    plymouth['generators']=[name for name in ('mkinitcpio','update-initramfs','dracut') if any((root/f'usr/{folder}/{name}').exists() for folder in ('bin','sbin'))]
    try:plymouth['mkinitcpio']=_static_presets(root)
    except (ValueError,OSError) as exc:
        plymouth['mkinitcpio']={'presets':[],'outputs':[],'inputs':[],'errors':[str(exc)],'uki_evidence':[]}
    result['inputs']+=plymouth['mkinitcpio']['presets']+plymouth['mkinitcpio']['inputs']
    for mount in ('boot','efi','boot/efi'):
        base=root/mount
        if (base/'loader/loader.conf').exists():result['bootloader']['candidates'].append('systemd-boot')
        if (base/'grub/grub.cfg').exists() or (base/'grub2/grub.cfg').exists():result['bootloader']['candidates'].append('grub')
        for image in _safe_glob(root,'/'+mount+'/EFI/Linux','*.efi',warnings):
            try:sections=pe_sections(image)
            except (OSError,ValueError) as exc:warnings.append(str(exc));continue
            if '.linux' in sections:
                path=relative(image);result['uki']['images'].append(path)
                if '.splash' in sections:result['uki']['static_splash'].append(path)
        for entry in _safe_glob(root,'/'+mount+'/loader/entries','*.conf',warnings):
            if re.search(r'(?m)^options\s+.*\bsplash\b',read(relative(entry))):plymouth['splash_enabled']=True
    for path in ['/etc/kernel/uki.conf','/etc/systemd/ukify.conf','/etc/kernel/install.conf']:
        text=read(path)
        if re.search(r'(?im)^\s*(?:Layout\s*=\s*uki|Splash\s*=|SecureBootPrivateKey\s*=|PCRPrivateKey\s*=)',text):
            result['uki']['configuration'].append(path)
    for path in ['/etc/kernel/cmdline','/etc/default/grub']:
        text='\n'.join(line for line in read(path).splitlines() if not line.lstrip().startswith('#'))
        if re.search(r'(?:^|[\s"\'])splash(?:[\s"\']|$)',text):plymouth['splash_enabled']=True
    # /proc describes the host, never an offline root or test fixture.
    if root==Path('/'):
        try:plymouth['splash_enabled']='splash' in Path('/proc/cmdline').read_text().split()
        except OSError:pass
    result['uki']['configuration']+=plymouth['mkinitcpio']['uki_evidence']
    result['bootloader']['candidates']=sorted(set(result['bootloader']['candidates']))
    result['inputs']=sorted(set(result['inputs']))
    if root==Path('/'):
        try:
            reply=readonly_run(['bootctl','status','--no-pager'],capture_output=True,text=True,timeout=6)
            section=re.search(r'(?s)Current Boot Loader:(.*?)(?:\n\S|$)',reply.stdout)
            if section:
                text=section[1]
                if re.search(r'Product:\s*systemd-boot',text,re.I):result['bootloader']['active']='systemd-boot'
                elif re.search(r'Product:.*GRUB',text,re.I):result['bootloader']['active']='grub'
            result['bootloader']['evidence'].append({'source':'bootctl status','returncode':reply.returncode})
        except (OSError,subprocess.SubprocessError) as exc:warnings.append('Active bootloader unavailable: '+str(exc))
    return result


def _theme_inputs(root,directory):
    directory=_system(root,directory);result={};total=0
    for actual in sorted(directory.rglob('*')):
        path='/'+actual.relative_to(root).as_posix();_system(root,path)
        if actual.is_dir():continue
        state=_state(actual);total+=state['size']
        if len(result)>=4096 or total>128*1024*1024:raise ValueError('Theme exceeds automatic review size limit')
        result[path]=state
    return result


def plan(login_theme='preserve',boot_theme='preserve',*,root=Path('/'),runner=subprocess.run,
         login_only=False,release_login=False):
    if (login_only and boot_theme!='preserve') or (release_login and (not login_only or login_theme!='preserve')):
        raise ValueError('Invalid login theme operation')
    info=detect(root,runner,login_only=login_only);root=Path(info['root'])
    result={'schema_version':SCHEMA,'root':str(root),'selection':{'login_theme':login_theme,'boot_theme':boot_theme},
            'detected':info,'packages':[],'changes':[],'artifacts':[],'commands':[],'conflicts':[],'unsupported':[],
            'inputs':{},'activation':[],
            'preserve':['display-manager selection','bootloader/default boot entry','existing desktops','UKI signing keys']}
    def conflict(text):result['conflicts'].append(text)
    def unsupported(text):result['unsupported'].append(text);conflict(text)
    if login_only:result['selection']['login_only']=True
    if release_login:result['selection']['release_login']=True
    def inputs(paths):
        for path in paths:result['inputs'][path]=_state(_system(root,path))
    def change(path,text):
        actual=_system(root,path)
        if actual.exists() and actual.read_text()==text:return False
        result['changes'].append({'path':path,'before':_state(actual),'content':text});return True
    if login_theme=='preserve' and boot_theme=='preserve' and not login_only:
        result['status']='preserved';return result
    if any(not isinstance(value,str) or (value!='preserve' and not NAME.fullmatch(value)) for value in [login_theme,boot_theme]):
        conflict('Theme names must be installed simple names, never paths or shell fragments')
    for warning in info['warnings']:
        if not warning.startswith('Active bootloader unavailable:'):conflict('Inspection incomplete: '+warning)
    try:
        if login_only or login_theme!='preserve':
            owned_file=_system(root,SDDM_FRAGMENT)
            old=_read(root,SDDM_FRAGMENT)
            owned=owned_sddm_fragment(old)
            if info['login_manager']['id']!='sddm':unsupported('Automatic login themes support only the selected SDDM; existing login manager is preserved')
            elif owned_file.exists() and not owned:conflict('ADWS SDDM fragment path is occupied by user content')
            elif release_login:
                if owned:
                    inputs(path for path in info['inputs'] if '/sddm' in path)
                    result['changes'].append({'path':SDDM_FRAGMENT,'before':_state(owned_file),'content':None})
                    result['activation'].append('next_login; current login manager is not restarted')
            elif login_theme not in info['sddm']['themes']:conflict('Requested SDDM theme is not already installed and complete')
            elif info['sddm']['shadowing_current'] not in (None,login_theme):conflict('/etc/sddm.conf overrides Theme.Current; resolve that existing user setting explicitly')
            elif info['sddm'].get('later_overrides'):conflict('A later SDDM user override takes priority over the ADWS theme fragment')
            else:
                inputs(path for path in info['inputs'] if '/sddm' in path)
                theme_path=info['sddm']['theme_dir']+'/'+login_theme
                if login_only:
                    metadata=theme_path+'/metadata.desktop'
                    main=_ini(_read(root,metadata)).get('SddmGreeterTheme','MainScript',fallback='Main.qml')
                    inputs((metadata,theme_path+'/'+main))
                else:
                    result['inputs'].update(_theme_inputs(root,theme_path))
                if change(SDDM_FRAGMENT,MARKER+'\n[Theme]\nCurrent='+login_theme+'\n'):
                    result['activation'].append('next_login; current login manager is not restarted')
        if boot_theme!='preserve':
            ply=info['plymouth'];mk=ply['mkinitcpio']
            if not ply['installed'] or boot_theme not in ply['themes']:conflict('Plymouth and the requested theme/module must already be installed')
            if info['uki']['images'] or info['uki']['configuration']:unsupported('UKI or signing/static-splash pipeline detected; do not rebuild it as a classic initramfs')
            if info['uki']['static_splash']:conflict('Existing UKI .splash remains selected; layering Plymouth requires explicit separate review')
            if ply['generators']!=['mkinitcpio'] or not (root/'usr/bin/mkinitcpio').is_file():unsupported('Only an unambiguous classic /usr/bin/mkinitcpio pipeline is supported automatically')
            elif root==Path('/'):
                try:
                    help_reply=runner(['/usr/bin/mkinitcpio','--help'],capture_output=True,text=True,timeout=6,env=dict(SYSTEM_ENV))
                    if help_reply.returncode!=0 or '--nopost' not in help_reply.stdout:unsupported('Installed mkinitcpio does not confirm --nopost support')
                except (OSError,subprocess.SubprocessError) as exc:unsupported('Cannot verify mkinitcpio --nopost support: '+str(exc))
            if not ply['hook']:conflict('Plymouth hook is not enabled; existing boot hooks are preserved')
            if not ply['splash_enabled']:conflict('No active splash boot parameter; existing kernel command line is preserved')
            result['conflicts']+=mk['errors']
            if not mk['presets'] or not mk['outputs']:conflict('No complete static initramfs preset/output inventory')
            if not result['conflicts']:
                inputs(path for path in info['inputs'] if '/sddm' not in path)
                inputs(['/usr/bin/mkinitcpio',ply['theme_modules'][boot_theme]])
                result['inputs'].update(_theme_inputs(root,'/usr/share/plymouth/themes/'+boot_theme))
                artifacts=[{'path':p,'before':_state(_system(root,p))} for p in mk['outputs']]
                if any(not row['before'] or not row['before']['size'] for row in artifacts):conflict('Existing initramfs image missing or empty; first-time boot setup requires separate review')
                if not result['conflicts']:
                    path='/etc/plymouth/plymouthd.conf'
                    if change(path,_set_ini(_read(root,path),'Daemon','Theme',boot_theme)):
                        result['artifacts']=artifacts
                        result['commands']=[['/usr/bin/mkinitcpio','--nopost','--preset',p] for p in mk['presets']]
                        result['activation'].append('next_reboot; verify boot appearance and keep rollback backup')
    except (ValueError,OSError,UnicodeError,configparser.Error) as exc:conflict(str(exc))
    result['status']='conflicts' if result['conflicts'] else 'preserved' if not result['changes'] else 'ready'
    return result


def _atomic(path,content,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.adws-boot-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno());os.fchmod(stream.fileno(),mode)
        os.replace(name,path)
        parent_fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(parent_fd)
        finally:os.close(parent_fd)
    finally:Path(name).unlink(missing_ok=True)


def _save(directory,journal):_atomic(directory/'journal.json',(json.dumps(journal,ensure_ascii=False,indent=2)+'\n').encode(),0o600)


def _staged_presets(proposal,directory):
    """Redirect only inspected literal image assignments to private outputs."""
    root=Path(proposal['root']);folder=directory/'rebuild';folder.mkdir(mode=0o700)
    outputs={row['path']:folder/(str(index)+'.img') for index,row in enumerate(proposal['artifacts'])}
    commands=[]
    for index,command in enumerate(proposal['commands']):
        source=_read(root,command[-1]);lines=[];rewritten=set()
        for line in source.splitlines(keepends=True):
            match=re.fullmatch(r'\s*([A-Za-z_][A-Za-z0-9_]*_image)=(.*?)(?:\n)?',line)
            if match:
                original=_literal(match[2])
                if original not in outputs:raise ValueError('Unreviewed preset image output')
                line=match[1]+'='+shlex.quote(str(outputs[original]))+'\n';rewritten.add(original)
            lines.append(line)
        if not rewritten:raise ValueError('Preset contains no reviewed image outputs')
        target=folder/(str(index)+'.preset');_atomic(target,''.join(lines).encode(),0o600)
        commands.append([*command[:-1],str(target)])
    return commands,outputs


def _copy_atomic(source,target,mode,expected):
    fd,name=tempfile.mkstemp(prefix='.adws-image-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as output,source.open('rb') as input_file:
            shutil.copyfileobj(input_file,output);output.flush();os.fsync(output.fileno());os.fchmod(output.fileno(),mode)
        # Copying a large image can take seconds. Check again immediately before
        # replace, not only before copying. This is not a filesystem CAS against
        # an uncooperative writer in the final instruction-sized rename window.
        if _state(target)!=expected:raise RuntimeError('Target changed during atomic image copy: '+str(target))
        os.replace(name,target)
        fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:Path(name).unlink(missing_ok=True)


def _allowed(path,kind):
    pure=PurePosixPath(path)
    if not pure.is_absolute() or '..' in pure.parts:raise ValueError('Invalid change path')
    if kind=='config' and path not in ALLOWED_CONFIG:raise ValueError('Config target outside allowlist')
    if kind=='artifact' and (not path.startswith('/boot/') or not path.endswith('.img')):raise ValueError('Boot image outside allowlist')


def _check_backup_directory(directory,root):
    directory=Path(directory).absolute()
    if root==Path('/') and (not directory.is_relative_to(BACKUP_ROOT) or directory==BACKUP_ROOT):
        raise ValueError('System theme backups must use /var/lib/adws/boot-theme-backups/<unique-id>')
    for parent in [directory,*directory.parents]:
        if parent.is_symlink():raise ValueError('Backup directory has symlink ancestors')
    if root==Path('/'):
        for path in (BACKUP_ROOT,directory):
            if path.exists() and (path.stat().st_uid!=0 or path.stat().st_mode & 0o022):
                raise ValueError('Privileged backups must be root-owned and not writable by other users')
    return directory


@contextmanager
def _lock(root):
    path=_system(root,'/run/lock/adws-boot-themes.lock')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise RuntimeError('Another ADWS boot-theme transaction is running') from exc
        yield
    finally:os.close(fd)


def _verify_inputs(proposal,overrides=None):
    root=Path(proposal['root']);overrides=overrides or {}
    for path,expected in proposal['inputs'].items():
        if _state(_system(root,path))!=overrides.get(path,expected):
            raise ValueError('Reviewed configuration/theme source changed: '+path)
    if proposal['commands'] and _system(root,'/var/lib/pacman/db.lck').exists():
        raise RuntimeError('Package transaction in progress; retry the reviewed theme step after it finishes')


def _result(journal,directory):
    return {'status':'applied-pending-session-validation','backup':str(directory),
            'activation':journal['activation'],'selection':journal['selection'],
            'changed':[dict(entry) for entry in journal['entries']],
            'verification':{'login':'pending-next-login' if journal['selection']['login_theme']!='preserve' or journal['selection'].get('login_only') else 'preserved',
                            'boot':'pending-next-reboot' if journal['selection']['boot_theme']!='preserve' else 'preserved'}}


def apply(proposal,backup_dir,*,runner=None):
    if proposal.get('schema_version')!=SCHEMA or proposal.get('conflicts'):raise ValueError('Unresolved boot-theme plan')
    if proposal.get('selection')=={'login_theme':'preserve','boot_theme':'preserve'}:
        if any(proposal.get(key) for key in ('changes','artifacts','commands')):raise ValueError('Preserve plan cannot contain changes')
        return {'status':'preserved','backup':None,'changed':[]}
    root=Path(proposal['root']).resolve()
    if root==Path('/') and os.geteuid()!=0:raise PermissionError('Optional system themes require administrator authorization')
    if root!=Path('/') and runner is None:raise ValueError('Fixture/offline-root application requires an explicit test rebuild runner')
    with _lock(root):return _apply_locked(proposal,backup_dir,runner or subprocess.run)


def _apply_locked(proposal,backup_dir,run):
    root=Path(proposal['root']).resolve()
    # Regenerate commands/destinations from detected facts; never execute JSON-supplied argv.
    current=plan(**proposal['selection'],root=root,runner=run)
    for key in ('changes','artifacts','commands','conflicts','inputs'):
        if current[key]!=proposal[key]:raise ValueError('System configuration changed after theme review: '+key)
    if not proposal['changes']:return {'status':'preserved','backup':None,'changed':[]}
    directory=_check_backup_directory(backup_dir,root)
    entries=[]
    for kind,key in [('config','changes'),('artifact','artifacts')]:
        for row in proposal[key]:
            _allowed(row['path'],kind)
            # Persist the intended config hash before writing: interruption recovery
            # can distinguish this write from a later administrator edit.
            after=None
            if kind=='config' and row['content'] is not None:
                content=row['content'].encode()
                after={'sha256':hashlib.sha256(content).hexdigest(),'size':len(content),
                       'mode':row['before']['mode'] if row['before'] else 0o644}
            entries.append({'kind':kind,'path':row['path'],'before':row['before'],'after':after})
    _verify_inputs(proposal)
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    # Reserve space for both verified old backups and private rebuilt images.
    required=sum(e['before']['size'] for e in entries if e['before'])
    required+=sum(e['before']['size'] for e in entries if e['kind']=='artifact' and e['before'])
    if shutil.disk_usage(directory).free<required+64*1024*1024:raise OSError('Insufficient space for complete boot artifact backups')
    for entry in entries:
        if entry['kind']=='artifact' and shutil.disk_usage(_system(root,entry['path']).parent).free<entry['before']['size']+8*1024*1024:
            raise OSError('Insufficient free boot storage for rebuild and atomic rollback')
    journal={'schema_version':SCHEMA,'root':str(root),'status':'backing-up','selection':proposal['selection'],
             'activation':proposal['activation'],'inputs':proposal['inputs'],'entries':entries}
    _save(directory,journal)
    for index,entry in enumerate(entries):
        source=_system(root,entry['path'])
        if _state(source)!=entry['before']:raise ValueError('System file changed before backup')
        if entry['before'] is not None:
            shutil.copy2(source,directory/f'{index}.original')
            if _state(directory/f'{index}.original')!=entry['before']:raise ValueError('Backup verification failed')
    _verify_inputs(proposal)
    journal['status']='applying';_save(directory,journal)
    overrides={}
    try:
        for row in proposal['changes']:
            target=_system(root,row['path'])
            if _state(target)!=row['before']:raise ValueError('Config changed during theme application')
            if row['content'] is None:
                target.unlink()
            else:
                _atomic(target,row['content'].encode(),row['before']['mode'] if row['before'] else 0o644)
            overrides[row['path']]=_state(target)
        staged_commands,outputs=_staged_presets(proposal,directory) if current['commands'] else ([],{})
        for command in staged_commands:
            _verify_inputs(proposal,overrides)
            journal['running_command']=command;_save(directory,journal)
            rebuild=_run_rebuild if run is subprocess.run else run
            reply=rebuild(command,check=True,timeout=600,env=dict(SYSTEM_ENV))
            if getattr(reply,'returncode',0)!=0:raise RuntimeError('Initramfs rebuild failed')
            journal.pop('running_command',None);_save(directory,journal)
        # Never adopt arbitrary changes made to /boot while a rebuild was active.
        # Only our private files may become the known after-state for rollback.
        for entry in entries:
            if entry['kind']!='artifact':continue
            target=_system(root,entry['path']);staged=outputs[entry['path']]
            after=_state(staged)
            if not after or not after['size']:raise RuntimeError('Rebuild produced no complete private image')
            if _state(target)!=entry['before']:raise RuntimeError('Boot image changed during rebuild: '+entry['path'])
            entry['after']={**after,'mode':entry['before']['mode']};_save(directory,journal)
            _copy_atomic(staged,target,entry['after']['mode'],entry['before'])
        for entry in entries:
            actual=_state(_system(root,entry['path']))
            if entry['kind']=='config' and actual!=entry['after']:raise RuntimeError('Theme config changed during rebuild: '+entry['path'])
            if entry['kind']=='artifact' and (actual is None or actual['size']==0):raise RuntimeError('Initramfs rebuild did not produce a nonempty output')
        journal['status']='applied';journal['result']=_result(journal,directory);_save(directory,journal)
    except BaseException as error:
        # Never claim an unrelated concurrent config edit as our own after-state.
        with _ignore_cancellation():
            if isinstance(error,_WritersRunning):
                journal['status']='recovery-blocked';journal['running_writers']=error.writers;_save(directory,journal);raise
            journal['status']='failed';_save(directory,journal)
            recovery=_rollback_locked(directory,journal)
            if recovery['conflicts']:raise RuntimeError('Theme application failed and rollback needs attention: '+str(recovery['conflicts']))
        raise
    return journal['result']


def rollback(backup_dir):
    directory=Path(backup_dir).absolute()
    for parent in [directory,*directory.parents]:
        if parent.is_symlink():raise ValueError('Rollback directory has symlink ancestors')
    if (directory/'journal.json').is_symlink():raise ValueError('Rollback journal must not be a symlink')
    journal=json.loads((directory/'journal.json').read_text());root=Path(journal['root']).resolve()
    if journal.get('schema_version')!=SCHEMA:raise ValueError('Unsupported theme rollback journal')
    if root==Path('/') and os.geteuid()!=0:raise PermissionError('Theme rollback needs administrator authorization')
    _check_backup_directory(directory,root)
    with _lock(root):return _rollback_locked(directory,journal)


def _rollback_locked(directory,journal):
    root=Path(journal['root']).resolve();conflicts=[];restored=[]
    processes=_process_table()
    if any(int(pid) in processes and processes[int(pid)]['start']==start and processes[int(pid)]['state']!='Z'
           for pid,start in journal.get('running_writers',{}).items()):
        raise RuntimeError('Rebuild writers are still active; refusing concurrent rollback')
    # Validate the whole journal before any restore, including unknown entry kinds.
    seen=set()
    for entry in journal['entries']:
        if entry['kind'] not in ('config','artifact'):raise ValueError('Unknown rollback entry kind')
        _allowed(entry['path'],entry['kind']);_system(root,entry['path'])
        if entry['path'] in seen:raise ValueError('Duplicate rollback path')
        seen.add(entry['path'])
    for index in reversed(range(len(journal['entries']))):
        entry=journal['entries'][index];target=_system(root,entry['path'])
        current=_state(target)
        if current==entry['before']:continue
        if current!=entry['after'] or (entry['kind']=='artifact' and entry['after'] is None):
            conflicts.append(entry['path']+': changed after theme application or interrupted rebuild');continue
        if entry['before'] is None:target.unlink(missing_ok=True)
        else:
            backup=directory/f'{index}.original'
            if _state(backup)!=entry['before']:conflicts.append(entry['path']+': backup integrity mismatch');continue
            # Stream boot images through a temporary file; never hold them in RAM.
            fd,name=tempfile.mkstemp(prefix='.adws-restore-',dir=target.parent);os.close(fd)
            try:
                shutil.copy2(backup,name)
                with open(name,'rb') as stream:os.fsync(stream.fileno())
                if _state(target)!=current:
                    conflicts.append(entry['path']+': changed while preparing rollback');continue
                os.replace(name,target)
            finally:Path(name).unlink(missing_ok=True)
        restored.append(entry['path'])
    journal['status']='rollback-conflicts' if conflicts else 'rolled-back';journal['rollback_conflicts']=conflicts;_save(directory,journal)
    return {'status':journal['status'],'backup':str(directory),'restored':restored,'conflicts':conflicts}


def operation_backup(directory):
    """Durable recovery address, available even if sudo returned no JSON."""
    path=Path(directory)/'system-theme-operation.json'
    if not path.is_file():return None
    operation=json.loads(path.read_text());identifier=operation.get('backup_id','')
    if not re.fullmatch(r'[0-9a-f]{32}',identifier):raise ValueError('Invalid recorded theme operation identity')
    if operation.get('state') in ('not-started','rolled-back'):return None
    if operation.get('state')=='recovery-still-running':
        raise RuntimeError('Privileged theme recovery is still running; do not start another rollback. Backup: '+str(BACKUP_ROOT/identifier))
    if operation.get('state')=='starting' and not operation.get('helper_pid'):return None
    return str(BACKUP_ROOT/identifier)


def invoke(proposal,directory,*,rollback=None):
    """Invoke the privileged helper cooperatively; never SIGKILL a recovery.

    The outer workflow may call operation_backup() in its exception handler to
    cover cancellation immediately after this function returned successfully.
    """
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    helper=Path(proposal['source_root'])/'tools/adws_install_boot_themes.py'
    command=[sys.executable,str(helper)]
    operation=None
    if rollback:
        command+=['--rollback',str(rollback)];backup=str(rollback)
    else:
        identifier=uuid.uuid4().hex;backup=str(BACKUP_ROOT/identifier)
        operation={'schema_version':1,'backup_id':identifier,'backup':backup,'state':'starting'}
        _atomic(directory/'system-theme-operation.json',(json.dumps(operation,indent=2)+'\n').encode(),0o600)
        path=directory/'system-theme-plan.json'
        _atomic(path,(json.dumps(proposal['theme_plan'],indent=2)+'\n').encode(),0o600)
        command+=['--apply-plan',str(path),'--backup-id',identifier]
    if os.geteuid()!=0:command=['sudo','--',*command]
    log_path=directory/('system-theme-rollback-helper.log' if rollback else 'system-theme-helper.log')
    child=None;error=None
    with log_path.open('w') as log:
        try:
            # Keep sudo/password/error prompts visible. The workflow already
            # tees stderr to the installation log; stdout is our helper protocol.
            with _defer_cancellation():
                child=subprocess.Popen(command,stdout=log)
                if operation:
                    operation.update(state='running',helper_pid=child.pid)
                    _atomic(directory/'system-theme-operation.json',(json.dumps(operation,indent=2)+'\n').encode(),0o600)
            child.wait()
        except BaseException as caught:
            error=caught
            if child is not None and child.poll() is None:
                with _ignore_cancellation():
                    # sudo forwards TERM to its command; the helper handles it,
                    # stops its rebuild descendants and restores before exiting.
                    try:child.send_signal(signal.SIGTERM)
                    except ProcessLookupError:pass
                    try:child.wait(timeout=660)
                    except subprocess.TimeoutExpired:
                        if operation:
                            operation['state']='recovery-still-running'
                            _atomic(directory/'system-theme-operation.json',(json.dumps(operation,indent=2)+'\n').encode(),0o600)
                        raise RuntimeError('Privileged recovery is still running; do not start another rebuild. Backup: '+backup) from caught
    authorized=False;output_unknown=True
    try:
        with log_path.open('rb') as log:
            header=log.read(65536).decode(errors='replace').splitlines()
            log.seek(max(0,log_path.stat().st_size-65536));lines=log.read().decode(errors='replace').strip().splitlines()
        authorized=any(line==json.dumps({'status':'authorized','backup':backup}) for line in header+lines)
        output_unknown=bool(''.join(header+lines).strip()) and not authorized
        result=json.loads(lines[-1])
    except (ValueError,IndexError):result={}
    failed=error is not None or child is None or child.returncode!=0 or not isinstance(result,dict) or 'status' not in result
    if operation:
        operation.update(state='failed' if failed else 'applied',result=result)
        _atomic(directory/'system-theme-operation.json',(json.dumps(operation,indent=2)+'\n').encode(),0o600)
    if failed:
        recovery=None
        if not rollback:
            recovered=result.get('recovery_status') if isinstance(result,dict) else None
            if recovered in ('rolled-back','not-started') or (not authorized and not output_unknown):
                recovery={'exit':0,'backup':backup,'status':recovered or 'not-started'}
                if operation:
                    operation.update(state=recovery['status'],recovery=recovery)
                    _atomic(directory/'system-theme-operation.json',(json.dumps(operation,indent=2)+'\n').encode(),0o600)
                if error is not None:raise error
                raise RuntimeError('System theme helper did not complete; '+recovery['status']+'. Backup: '+backup)
            with _ignore_cancellation():
                # Do not prompt again after cancellation of an authorization
                # dialog. A cached ticket can perform idempotent recovery; lack
                # of authorization is reported alongside the known backup.
                recover=[sys.executable,str(helper),'--rollback',backup]
                if os.geteuid()!=0:recover=['sudo','-n','--',*recover]
                with (directory/'system-theme-recovery-helper.log').open('w') as log:
                    process=subprocess.Popen(recover,stdout=log);process.wait()
                recovery={'exit':process.returncode,'backup':backup}
                if operation:
                    operation['recovery']=recovery
                    if process.returncode==0:operation['state']='rolled-back'
                    _atomic(directory/'system-theme-operation.json',(json.dumps(operation,indent=2)+'\n').encode(),0o600)
        if recovery and recovery['exit']!=0:
            raise RuntimeError('System theme cancellation/failure needs recovery review. Backup: '+backup) from error
        if error is not None:raise error
        raise RuntimeError('System theme helper failed; recovery attempted. Backup: '+backup)
    if not isinstance(result,dict) or 'status' not in result:
        raise RuntimeError('System theme helper returned no valid result. Backup: '+backup)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--inspect',action='store_true');parser.add_argument('--apply-plan');parser.add_argument('--rollback');parser.add_argument('--backup-id')
    args=parser.parse_args(argv)
    if args.inspect:print(json.dumps(detect(),ensure_ascii=False,indent=2));return 0
    if args.rollback:
        location=Path(args.rollback).absolute()
        _check_backup_directory(location,Path('/'))
        if not (location/'journal.json').exists():
            print(json.dumps({'status':'not-started','backup':str(location),'restored':[],'conflicts':[]}));return 0
        if json.loads((location/'journal.json').read_text()).get('root')!='/':raise ValueError('Privileged rollback only accepts the current system root')
        with _ignore_cancellation():result=rollback(location)
        print(json.dumps(result,ensure_ascii=False));return 1 if result['conflicts'] else 0
    if args.apply_plan:
        identifier=args.backup_id or uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}',identifier):raise ValueError('Invalid theme backup identity')
        proposal=json.loads(Path(args.apply_plan).read_text())
        if proposal.get('root')!='/':raise ValueError('Privileged helper only accepts the current system root')
        if os.geteuid()!=0:raise PermissionError('System theme helper requires administrator authorization')
        print(json.dumps({'status':'authorized','backup':str(BACKUP_ROOT/identifier)}),flush=True)
        try:
            with _cancellation_signals():result=apply(proposal,BACKUP_ROOT/identifier)
        except BaseException as error:
            journal=BACKUP_ROOT/identifier/'journal.json'
            try:recovery=json.loads(journal.read_text()).get('status','unknown') if journal.exists() else 'not-started'
            except (OSError,ValueError):recovery='unknown'
            print(json.dumps({'status':'cancelled' if isinstance(error,KeyboardInterrupt) else 'failed','backup':str(BACKUP_ROOT/identifier),'recovery_status':recovery,'error':str(error)},ensure_ascii=False))
            return 130 if isinstance(error,KeyboardInterrupt) else 1
        print(json.dumps(result,ensure_ascii=False));return 0
    parser.error('Select --inspect, --apply-plan or --rollback')

if __name__=='__main__':raise SystemExit(main())

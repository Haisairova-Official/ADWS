"""Optional Matugen palette extraction and explicit package management."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from adws_i18n import tr as _tr


def package_manager():
    return next((p for p in ('pacman','apt-get','dnf') if shutil.which(p)),None)


def status():
    binary=shutil.which('matugen'); manager=package_manager(); package=None
    if binary and manager:
        command={'pacman':['pacman','-Qoq',str(Path(binary).resolve())],
                 'apt-get':['dpkg-query','-S',str(Path(binary).resolve())],
                 'dnf':['rpm','-qf','--qf','%{NAME}',str(Path(binary).resolve())]}[manager]
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=4)
            name=result.stdout.strip().splitlines()[0].split(':')[0] if result.returncode==0 else ''
            if name in ('matugen','matugen-bin'):package=name
        except (OSError,subprocess.SubprocessError,IndexError):pass
    return {'installed':bool(binary),'package':package,'manager':manager}


def package_command(remove=False, snapshot=None):
    data=snapshot or status();manager=data['manager']
    if not manager:raise ValueError(_tr('此系统不支持自动管理 Matugen，请使用系统软件管理器。'))
    package=data['package'] if remove else 'matugen'
    if remove and package not in ('matugen','matugen-bin'):
        raise ValueError(_tr('Matugen 不是由系统软件包安装的，请通过原安装方式卸载。'))
    args={'pacman':['pacman','-R' if remove else '-S',*(['--needed'] if not remove else []),'--noconfirm',package],
          'apt-get':['apt-get','remove' if remove else 'install','-y',package],
          'dnf':['dnf','remove' if remove else 'install',*(['--setopt=clean_requirements_on_remove=False'] if remove else []),'-y',package]}[manager]
    if os.geteuid()!=0:
        if not shutil.which('pkexec'):raise ValueError(_tr('缺少 pkexec，请先安装系统授权组件。'))
        args.insert(0,'pkexec')
    return args


def manage(remove=False):
    result=subprocess.run(package_command(remove),capture_output=True,text=True,timeout=600)
    if result.returncode:
        raise RuntimeError(_tr('Matugen 软件包操作未完成。')+'\n'+(result.stderr or result.stdout)[-1500:])
    if not remove and not shutil.which('matugen'):raise RuntimeError(_tr('Matugen 软件包操作未完成。'))


def parse_palette(data, mode="dark"):
    colors=data.get('colors',{})
    # Matugen 4 uses colors.<role>.default.color; earlier releases used
    # colors.dark.<role> or colors.<role>.default.hex.
    if isinstance(colors.get(mode),dict):colors=colors[mode]
    result={}
    for name,value in colors.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*',name):continue
        if isinstance(value,dict):value=value.get('default',value)
        if isinstance(value,dict):value=value.get('color',value.get('hex'))
        if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value):result[name]=value
    required={'surface','surface_container','surface_container_high','on_surface','on_surface_variant','primary','on_primary','outline_variant','error'}
    if not required.issubset(result):raise ValueError(_tr('配色结果不完整，保留现有配色。'))
    return result


SCHEMES = ('scheme-tonal-spot', 'scheme-vibrant', 'scheme-fruit-salad', 'scheme-fidelity',
           'scheme-expressive', 'scheme-neutral', 'scheme-monochrome', 'scheme-rainbow', 'scheme-content')


def preferences_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/color-scheme.json'


def validate_preferences(data):
    scheme=data.get('scheme', 'scheme-tonal-spot');mode=data.get('mode','dark');index=data.get('index',0)
    if scheme not in SCHEMES or mode not in ('dark','light') or type(index) is not int or not 0<=index<=4:
        raise ValueError(_tr('配色方案无效。'))
    result={'scheme':scheme,'mode':mode,'index':index}
    if 'index_mode' in data:
        if data['index_mode'] not in ('first','cycle'):raise ValueError(_tr('配色方案无效。'))
        result['index_mode']=data['index_mode']
    return result


def preferences():
    try:return validate_preferences(json.loads(preferences_path().read_text()))
    except (OSError,ValueError,TypeError,AttributeError):return validate_preferences({})


def save_preferences(data):
    from adws_atomic import replace_files
    replace_files({preferences_path():(json.dumps(validate_preferences(data))+'\n').encode()})


def extract(image, settings=None):
    selected=validate_preferences(settings) if settings is not None else preferences()
    if selected.get('index_mode')=='cycle':selected['index']=(selected['index']+1)%5
    elif selected.get('index_mode')=='first':selected['index']=0
    binary=shutil.which('matugen')
    if not binary:raise ValueError(_tr('请先安装 Matugen，再启用自动提取主体色。'))
    image=Path(image).expanduser().resolve(strict=True)
    # Ignore user hooks/config: only ADWS's palette is changed, never wallpaper
    # daemons, other terminal themes or arbitrary third-party reload scripts.
    with tempfile.TemporaryDirectory(prefix='adws-palette-') as directory:
        config=Path(directory)/'config.toml';config.write_text('[config]\n[templates]\n')
        help_output=subprocess.run([binary,'image','--help'],capture_output=True,text=True,timeout=5).stdout
        args=[binary,'--config',str(config),'--dry-run','--json','hex','image',str(image), '--type',selected['scheme'],'--mode',selected['mode']]
        if '--source-color-index' in help_output:args+=['--source-color-index',str(selected['index'])]
        if '--prefer' in help_output:args+=['--prefer','saturation']
        result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=45)
        if result.returncode and selected.get('index_mode')=='cycle' and '--source-color-index' in args:
            args[args.index('--source-color-index')+1]='0';selected['index']=0
            result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=45)
        if result.returncode:raise RuntimeError(_tr('主体色提取失败，保留现有配色。')+'\n'+result.stderr[-1500:])
        palette=parse_palette(json.loads(result.stdout), selected['mode'])
    target=Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'waybar/colors.css'
    # Preserve an existing user-managed symlink.
    target=target.resolve()
    from adws_terminal_presets import write
    content='/* Generated by ADWS with Matugen */\n'+''.join('@define-color '+name+' '+value+';\n' for name,value in sorted(palette.items()))
    if target.exists():
        backup=target.with_name(target.name+'.adws-colors.bak')
        shutil.copy2(target,backup)
    write(target,content)
    save_preferences(selected)
    return palette

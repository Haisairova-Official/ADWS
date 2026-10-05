"""Edit standalone Waybar without replacing its theme or touching ADWS's panel."""
import json
import os
from pathlib import Path
import re
import signal
import tempfile
from adws_i18n import tr as _tr
from adws_layout import _strip_jsonc, _drop_trailing_commas

LIMIT = 2 * 1024 * 1024

def folder():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'waybar'

def decode(text):
    if len(text.encode()) > LIMIT: raise ValueError(_tr('Waybar 配置过大。'))
    value = json.loads(_drop_trailing_commas(_strip_jsonc(text)))
    bars = value if isinstance(value, list) else [value]
    if not bars or not all(isinstance(bar, dict) for bar in bars):
        raise ValueError(_tr('Waybar 配置必须是对象或对象列表。'))
    return value

def is_adws(path):
    return bool({Path(path).name,Path(path).resolve().name} & {'config-bottom.jsonc','style-bottom.css'})

def default_config():
    return next((folder()/n for n in ('config','config.jsonc') if (folder()/n).is_file()), folder()/'config.jsonc')

def option(argv, short, long):
    for index, arg in enumerate(argv):
        if arg in (short,long): return argv[index+1] if index+1<len(argv) else None
        if arg.startswith(long+'='): return arg.split('=',1)[1]
        if arg.startswith(short) and len(arg)>len(short): return arg[len(short):]
    return None

def processes():
    result=[]
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal(): continue
        try:
            if directory.stat().st_uid != os.getuid() or (directory/'comm').read_text().strip()!='waybar':continue
            argv=(directory/'cmdline').read_bytes().decode().strip('\0').split('\0')
            if not argv or Path(argv[0]).name!='waybar':continue
            env=dict(item.split('=',1) for item in (directory/'environ').read_bytes().decode().split('\0') if '=' in item)
            base=Path(env.get('XDG_CONFIG_HOME') or str(Path(env.get('HOME',str(Path.home())))/'.config'))/'waybar'
            config=option(argv,'-c','--config')
            if config:
                config=Path(config).expanduser()
                if not config.is_absolute():config=(directory/'cwd').resolve()/config
            else:config=next((base/n for n in ('config','config.jsonc') if (base/n).is_file()),base/'config.jsonc')
            style=option(argv,'-s','--style')
            style=Path(style).expanduser() if style else base/'style.css'
            if not style.is_absolute():style=(directory/'cwd').resolve()/style
            if is_adws(config):continue
            result.append({'pid':int(directory.name),'config':config,'style':style,'argv':argv,'cwd':(directory/'cwd').resolve(),'start':(directory/'stat').read_text().rsplit(')',1)[1].split()[19]})
        except (OSError,ValueError,IndexError,UnicodeError):continue
    return result

def detect():
    running=processes()
    return running[0] if running else {'config':default_config(),'style':folder()/'style.css','pid':None}

# Tokens retain offsets, including strings containing comment punctuation. Only
# edited root values are replaced; unrelated comments and module definitions stay.
TOKENS=re.compile(r'//[^\r\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[{}\[\],:]|[^\s{}\[\],:]+')
def tokens(text):
    return [(m.group(),m.start(),m.end()) for m in TOKENS.finditer(text) if not m.group().startswith(('//','/*'))]

def object_spans(text):
    items=tokens(text);depth=0;starts=[];spans=[]
    for value,start,end in items:
        if value=='{':
            if depth==0 or (depth==1 and items[0][0]=='['):starts.append(start)
            depth+=1
        elif value=='[':depth+=1
        elif value in ('}',']'):
            depth-=1
            if value=='}' and starts and (depth==0 or depth==1 and items[0][0]=='['):spans.append((starts.pop(),end))
    return spans

def patch_object(text, changes):
    decode(text)
    items=tokens(text);depth=0;spans={}
    for i,(value,start,end) in enumerate(items):
        if depth==1 and value.startswith('"') and i+1<len(items) and items[i+1][0]==':':
            key=json.loads(value);j=i+2;level=0
            while j<len(items):
                token=items[j][0]
                if level==0 and token in (',','}'):break
                if token in ('{','['):level+=1
                elif token in ('}',']'):level-=1
                j+=1
            if key in spans:raise ValueError(_tr('Waybar 配置包含重复字段。'))
            spans[key]=(items[i+2][1],items[j-1][2])
        if value in ('{','['):depth+=1
        elif value in ('}',']'):depth-=1
    edits=[];missing={}
    for key,value in changes.items():
        if key in spans:
            a,b=spans[key];edits.append((a,b,json.dumps(value,ensure_ascii=False)))
        else:missing[key]=value
    for a,b,value in sorted(edits,reverse=True):text=text[:a]+value+text[b:]
    if missing:
        items=tokens(text);end=items[-1][1];has_values=len(items)>2;comma=',' if has_values and items[-2][0]!=',' else ''
        extra='\n'+',\n'.join('    '+json.dumps(k)+': '+json.dumps(v,ensure_ascii=False) for k,v in missing.items())+'\n'
        text=text[:end]+comma+extra+text[end:]
    decode(text);return text

def patch(text,index,changes):
    data=decode(text);bars=data if isinstance(data,list) else [data]
    if index<0 or index>=len(bars):raise ValueError(_tr('所选 Waybar 栏不存在。'))
    spans=object_spans(text);start,end=spans[index]
    return text[:start]+patch_object(text[start:end],changes)+text[end:]

def reload_allowed(config, seen=None):
    # Included files may override the signal action. Refuse to signal when any
    # loaded fragment requests a different action, rather than accidentally hide it.
    seen=set() if seen is None else seen
    path=Path(config).resolve()
    if path in seen:return True
    if len(seen)>=64:return False
    seen.add(path)
    try:
        data=decode(path.read_text());bars=data if isinstance(data,list) else [data]
        for bar in bars:
            if bar.get('on-sigusr2','reload')!='reload':return False
            includes=bar.get('include',[])
            if isinstance(includes,str):includes=[includes]
            if not isinstance(includes,list) or not all(isinstance(v,str) for v in includes):return False
            for name in includes:
                child=Path(os.path.expandvars(name)).expanduser()
                if not reload_allowed(child if child.is_absolute() else path.parent/child,seen):return False
    except (OSError,ValueError):return False
    return True

def reload(config):
    # Niri modules can crash during Waybar's in-process SIGUSR2 teardown.
    # Refresh via a normal, profile-scoped stop/start instead.
    matches=[p for p in processes() if p['config'].resolve()==Path(config).resolve()]
    style=matches[0]['style'] if matches else load_style(config)['path']
    restart(config,style)
    return 1


def restart(config, style):
    """Start/restart the selected standalone bar; never touch another profile."""
    import fcntl, hashlib, shutil, subprocess, time
    config=Path(config).expanduser().resolve();style=Path(style).expanduser().resolve()
    if is_adws(config) or is_adws(style):
        raise ValueError(_tr('请使用任务栏外观设置修改 ADWS 底栏。'))
    decode(config.read_text())
    if not style.is_file():raise FileNotFoundError(style)
    binary=shutil.which('waybar')
    if not binary:raise RuntimeError(_tr('未找到 Waybar。'))
    logs=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/waybar-logs'
    logs.mkdir(parents=True,exist_ok=True)
    identity=hashlib.sha256(str(config).encode()).hexdigest()[:16]
    lock=logs/(identity+'.lock');log=logs/(identity+'.log')
    with lock.open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        running=[p for p in processes() if p['config'].resolve()==config]
        if len(running)>1:raise RuntimeError(_tr('同一配置存在多个 Waybar 实例，请先关闭多余实例。'))
        argv=[binary,'-c',str(config),'-s',str(style)];cwd=config.parent
        if running:
            previous=running[0]
            current=next((p for p in processes() if p['pid']==previous['pid'] and p['start']==previous['start'] and p['config'].resolve()==config),None)
            if current:
                argv=current.get('argv',argv);cwd=current.get('cwd',cwd)
                os.kill(current['pid'],signal.SIGTERM)
                until=time.monotonic()+3
                while any(p['pid']==current['pid'] and p['start']==current['start'] for p in processes()):
                    if time.monotonic()>=until:raise RuntimeError(_tr('Waybar 未能正常退出，请稍后重试。'))
                    time.sleep(.05)
        with log.open('w') as output:
            child=subprocess.Popen(argv,cwd=cwd,stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
        time.sleep(.65)
        if child.poll() is not None:
            raise RuntimeError(_tr('Waybar 启动失败，日志：%s') % log)
        return {'pid':child.pid,'log':str(log)}


def save(config,original,content):
    config=Path(config).expanduser()
    if is_adws(config):raise ValueError(_tr('请使用任务栏外观设置修改 ADWS 底栏。'))
    decode(content)
    if config.read_text()!=original:raise ValueError(_tr('Waybar 配置已被其他程序修改，请重新加载后再试。'))
    target=config.resolve()
    backup=backup_current(config)
    from adws_atomic import replace_files
    commit_bundle(config,{config:content.encode()},backup)
    return {'backup':str(backup),'reloaded':1}


def module_catalog(path,data):
    """Read module names from includes once in the settings worker, never execute them."""
    names={'clock','tray','pulseaudio','wireplumber','backlight','battery','network','bluetooth','cpu','memory','mpris','idle_inhibitor'}
    visited=set()
    def walk(current,value):
        current=Path(current).resolve()
        if current in visited or len(visited)>=64:return
        visited.add(current)
        for bar in value if isinstance(value,list) else [value]:
            for key,item in bar.items():
                if isinstance(item,dict):names.add(key)
                elif key.startswith('modules-') and isinstance(item,list):names.update(v for v in item if isinstance(v,str))
            includes=bar.get('include',[])
            if isinstance(includes,str):includes=[includes]
            if not isinstance(includes,list):continue
            for include in includes:
                if not isinstance(include,str):continue
                included=Path(os.path.expandvars(include)).expanduser()
                if not included.is_absolute():included=current.parent/included
                try:walk(included,decode(included.read_text()))
                except (OSError,ValueError):continue
    walk(path,data)
    return sorted(names)

STYLE_BEGIN='/* ==== ADWS Waybar colors BEGIN ==== */'
STYLE_END='/* ==== ADWS Waybar colors END ==== */'
STYLE_PATTERN=re.compile(re.escape(STYLE_BEGIN)+r'.*?'+re.escape(STYLE_END),re.S)

def load_style(config):
    matches=[p for p in processes() if p['config'].resolve()==Path(config).resolve()]
    styles={p['style'].resolve() for p in matches}
    if len(styles)>1:raise ValueError(_tr('此配置使用多个样式文件，请手动指定样式路径。'))
    path=next(iter(styles),Path(config).parent/'style.css')
    text=path.read_text() if path.is_file() else ''
    match=STYLE_PATTERN.search(text);settings={}
    if match:
        metadata=re.search(r'/\* settings: (.*?) \*/',match.group())
        if metadata:
            try:settings=json.loads(metadata.group(1))
            except ValueError:pass
    font_match=FONT_PATTERN.search(text);font_settings={}
    if font_match:
        metadata=re.search(r'/\* settings: (.*?) \*/',font_match.group())
        if metadata:
            try:font_settings=json.loads(metadata.group(1))
            except ValueError:pass
    return {'path':path,'text':text,'settings':settings,'font_settings':font_settings}

def color_style(original,settings,data):
    clean=STYLE_PATTERN.sub('',original).rstrip()
    if settings.get('follow',True):return clean+'\n' if clean else ''
    defaults={'background':'#303030','foreground':'#ffffff','hover':'#555555','primary':'#ffb59e','secondary':'#eedbcf','tertiary':'#e8c6df'}
    colors={key:settings.get(key,value) for key,value in defaults.items()}
    for value in colors.values():
        if not isinstance(value,str) or not re.fullmatch(r'rgba?\([\d., %]+\)|#[0-9a-fA-F]{3,8}',value):
            raise ValueError(_tr('无效的颜色值'))
    lines=[STYLE_BEGIN,'/* settings: '+json.dumps({'follow':False,**colors},ensure_ascii=True)+' */']
    for role,key in [('surface_container_high','background'),('on_surface','foreground'),('primary','primary'),('secondary','secondary'),('tertiary','tertiary')]:
        lines.append('@define-color '+role+' '+colors[key]+';')
    selectors=set()
    for bar in data if isinstance(data,list) else [data]:
        for slot in ('modules-left','modules-center','modules-right'):
            for module in bar.get(slot,[]):
                if not isinstance(module,str) or '_div' in module:continue
                base=module.split('#',1)[0]
                name='custom-'+base[7:] if base.startswith('custom/') else base.rsplit('/',1)[-1]
                if re.fullmatch(r'[a-zA-Z][\w-]*',name):selectors.add('window#waybar #'+name+':hover')
    if selectors:lines.append(',\n'.join(sorted(selectors))+' { background-color: '+colors['hover']+'; }')
    lines.append(STYLE_END)
    return clean+'\n\n'+'\n'.join(lines)+'\n'

def save_with_style(config,original,content,style_path,style_original,style_content):
    config=Path(config);style_path=Path(style_path)
    if is_adws(config) or is_adws(style_path):raise ValueError(_tr('请使用任务栏外观设置修改 ADWS 底栏。'))
    decode(content)
    if config.read_text()!=original or (style_path.read_text() if style_path.exists() else '')!=style_original:
        raise ValueError(_tr('Waybar 配置已被其他程序修改，请重新加载后再试。'))
    if config.resolve()==style_path.resolve():raise ValueError(_tr('配置文件与样式文件不能相同。'))
    return save_bundle(config,original,content,style_path,style_original,style_content)


def replace_bar(text,index,bar):
    """Replace the chosen preset while retaining other bars and outer comments."""
    data=decode(text);bars=data if isinstance(data,list) else [data]
    if not 0<=index<len(bars):raise ValueError(_tr('所选 Waybar 栏不存在。'))
    start,end=object_spans(text)[index]
    content=text[:start]+json.dumps(bar,ensure_ascii=False,indent=2)+text[end:]
    decode(content);return content


def bundle_records(config,style=None,reader=None):
    """Collect includes, CSS imports and local CSS images without running commands."""
    config=Path(config).expanduser();style=None if style is False else Path(style).expanduser() if style else load_style(config)['path']
    if is_adws(config) or (style is not None and is_adws(style)):raise ValueError(_tr('请使用任务栏外观设置修改 ADWS 底栏。'))
    records={};total=0
    def collect(path,kind):
        nonlocal total
        path=Path(path).expanduser();real=path.resolve()
        if real in records:return
        if len(records)>=128:raise ValueError(_tr('配置引用过多，未创建备份。'))
        raw=reader(real) if reader else real.read_bytes()
        total+=len(raw)
        if len(raw)>16*1024*1024 or total>64*1024*1024:raise ValueError(_tr('配置文件过大，未创建备份。'))
        records[real]=(str(path),raw,kind)
        if kind=='config':
            value=decode(raw.decode('utf-8-sig'))
            for bar in value if isinstance(value,list) else [value]:
                refs=bar.get('include',[]);refs=[refs] if isinstance(refs,str) else refs
                if not isinstance(refs,list) or any(not isinstance(v,str) for v in refs):raise ValueError(_tr('include 格式无效。'))
                for ref in refs:collect(reference(path,ref),'config')
        elif kind=='style':
            text=re.sub(r'/\*.*?\*/','',raw.decode('utf-8-sig'),flags=re.S)
            imports=re.findall(r'@import\s+(?:url\(\s*)?["\']([^"\']+)["\']\s*\)?\s*;',text)
            for ref in imports:
                if not remote_reference(ref):collect(reference(path,ref),'style')
            for match in CSS_URL.finditer(text):
                ref=match.group(2).strip()
                if ref not in imports and not remote_reference(ref):collect(reference(path,ref),'asset')
    collect(config,'config')
    if style is not None and (reader or style.is_file()):collect(style,'style')
    return records

CSS_URL=re.compile(r'url\(\s*(["\']?)([^)]+?)\1\s*\)')

def remote_reference(value):
    return value.startswith(('data:','resource:','#')) or '://' in value

def reference(parent,value):
    path=Path(os.path.expandvars(value)).expanduser()
    return path if path.is_absolute() else parent.parent/path

def backup_current(config,style=None,destination=None):
    """Snapshot the complete local configuration graph, including CSS images."""
    import datetime,hashlib,shutil
    config=Path(config).expanduser();style=Path(style).expanduser() if style else load_style(config)['path']
    records=bundle_records(config,style)
    base=Path(destination) if destination else backup_folder()
    base.mkdir(parents=True,exist_ok=True)
    target=Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-',dir=base))
    manifest={'config':str(config),'style':str(style),'files':[]}
    try:
        for n,(real,(original,raw,kind)) in enumerate(records.items()):
            name=f'{n:02d}-'+real.name;(target/name).write_bytes(raw)
            manifest['files'].append({'source':original,'resolved':str(real),'snapshot':name,'sha256':hashlib.sha256(raw).hexdigest(),'kind':kind})
        (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    except Exception:
        shutil.rmtree(target);raise
    return target

def backup_folder():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/waybar-backups'

def import_bundle(source,config,style,source_style=None):
    """Copy an import into its own managed directory; do not depend on source files."""
    import uuid
    source=Path(source).expanduser().resolve();config=Path(config).expanduser().resolve();style=Path(style).expanduser().resolve()
    source_style=Path(source_style).expanduser().resolve() if source_style else source.parent/'style.css'
    if not source_style.is_file():raise ValueError(_tr('未找到样式文件，请选择配套 CSS。'))
    records=bundle_records(source,source_style)
    folder=config.parent/'adws-imports'/uuid.uuid4().hex
    targets={real:(config if real==source else style if real==source_style else folder/(str(n)+'-'+real.name)) for n,real in enumerate(records)}
    files={}
    for real,(original,raw,kind) in records.items():
        parent=Path(original)
        if kind=='config':
            text=raw.decode('utf-8-sig');data=decode(text)
            for index,bar in enumerate(data if isinstance(data,list) else [data]):
                refs=bar.get('include')
                if refs is None:continue
                values=[refs] if isinstance(refs,str) else refs
                mapped=[str(targets[reference(parent,v).resolve()]) for v in values]
                text=patch(text,index,{'include':mapped[0] if isinstance(refs,str) else mapped})
            raw=text.encode()
        elif kind=='style':
            text=raw.decode('utf-8-sig')
            def url(match):
                ref=match.group(2).strip()
                return match.group() if remote_reference(ref) else 'url('+json.dumps(str(targets[reference(parent,ref).resolve()]))+')'
            def css_import(match):
                ref=match.group(2)
                return match.group() if remote_reference(ref) else '@import '+json.dumps(str(targets[reference(parent,ref).resolve()]))+';'
            # Comments may contain example URLs which are not real assets.
            parts=re.split(r'(/\*.*?\*/)',text,flags=re.S)
            for i in range(0,len(parts),2):
                parts[i]=CSS_URL.sub(url,parts[i])
                parts[i]=re.sub(r'@import\s+(["\'])([^"\']+)\1\s*;',css_import,parts[i])
            raw=''.join(parts).encode()
        files[targets[real]]=raw
    text=files[config].decode();return {'text':text,'data':decode(text),'catalog':module_catalog(source,decode(records[source][1].decode('utf-8-sig'))),'style':files[style].decode(),'files':files,'count':len(files)}

def save_bundle(config,original,content,style,style_original,style_content,extra=None):
    from adws_atomic import replace_files
    config=Path(config);style=Path(style)
    decode(content)
    if config.read_text()!=original or (style.read_text() if style.exists() else '')!=style_original:raise ValueError(_tr('Waybar 配置已被其他程序修改，请重新加载后再试。'))
    if config.resolve()==style.resolve():raise ValueError(_tr('配置文件与样式文件不能相同。'))
    files={Path(p):raw for p,raw in (extra or {}).items() if Path(p).resolve() not in (config.resolve(),style.resolve())}
    managed=config.resolve().parent/'adws-imports'
    if any(not p.resolve().is_relative_to(managed) or p.exists() for p in files):raise ValueError(_tr('导入目标无效。'))
    backup=backup_current(config,style)
    files.update({config:content.encode(),style:style_content.encode()})
    commit_bundle(config,files,backup)
    return {'backup':str(backup),'reloaded':1}

def list_backups(config):
    config=Path(config).resolve();result=[]
    if not backup_folder().exists():return result
    for path in sorted(backup_folder().iterdir(),reverse=True):
        if (path.is_file() and path.name.startswith('config-') and path.suffix=='.jsonc') or (path.is_dir() and not (path/'manifest.json').exists() and (path/'config.jsonc').is_file() and (path/'style.css').is_file()):
            result.append(path);continue
        try:
            manifest=json.loads((path/'manifest.json').read_text())
            if Path(manifest['config']).resolve()==config:result.append(path)
        except (OSError,ValueError,KeyError,TypeError):continue
    return result

def restore_backup(directory,config,style):
    import hashlib
    from adws_atomic import replace_files
    directory=Path(directory).resolve();config=Path(config);style=Path(style)
    if is_adws(config) or is_adws(style):raise ValueError(_tr('请使用任务栏外观设置修改 ADWS 底栏。'))
    if not directory.is_relative_to(backup_folder().resolve()):raise ValueError(_tr('备份位置无效。'))
    if directory.is_file() or not (directory/'manifest.json').exists():
        if directory not in list_backups(config):raise ValueError(_tr('备份文件无效。'))
        files={config:(directory if directory.is_file() else directory/'config.jsonc').read_bytes()}
        decode(files[config].decode())
        if directory.is_dir():files[style]=(directory/'style.css').read_bytes()
        backup=backup_current(config,style);commit_bundle(config,files,backup)
        return {'backup':str(backup),'reloaded':1}
    manifest=json.loads((directory/'manifest.json').read_text())
    if Path(manifest['config']).resolve()!=config.resolve() or Path(manifest['style']).resolve()!=style.resolve():raise ValueError(_tr('备份不属于当前配置。'))
    snapshots={}
    for item in manifest['files']:
        filename=directory/item['snapshot']
        if filename.parent!=directory or filename.is_symlink():raise ValueError(_tr('备份文件无效。'))
        raw=filename.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError(_tr('备份校验失败。'))
        target=Path(item['source']).expanduser().resolve()
        if target!=Path(item['resolved']) or target in snapshots:raise ValueError(_tr('备份路径已变化。'))
        snapshots[target]=raw
    # Only restore files actually reachable from the selected roots. Extra
    # forged manifest destinations cannot turn restore into arbitrary writes.
    graph=bundle_records(config,style if style.resolve() in snapshots else False,reader=lambda p:snapshots[p])
    if set(graph)!=set(snapshots):raise ValueError(_tr('备份包含无关文件。'))
    backup=backup_current(config,style)
    commit_bundle(config,snapshots,backup)
    return {'backup':str(backup),'reloaded':1}


FONT_BEGIN='/* ==== ADWS Waybar font BEGIN ==== */'
FONT_END='/* ==== ADWS Waybar font END ==== */'
FONT_PATTERN=re.compile(re.escape(FONT_BEGIN)+r'.*?'+re.escape(FONT_END),re.S)

def font_style(original,settings):
    """Override text fonts only; icon fonts and palette overrides stay intact."""
    clean=FONT_PATTERN.sub('',original).rstrip()
    family=settings.get('family','Sans')
    size=settings.get('size',10)
    if not isinstance(family,str) or not family.strip() or any(ord(c)<32 for c in family):raise ValueError(_tr('无效的字体'))
    if isinstance(size,bool) or not isinstance(size,(int,float)) or not 6<=size<=48:raise ValueError(_tr('字体大小应为 6–48。'))
    metadata={'follow':bool(settings.get('follow',True)),'family':family,'size':size}
    css='window#waybar #window, window#waybar #clock, tooltip label { font-family: '+json.dumps(family,ensure_ascii=False)+'; font-size: '+str(size)+'pt; }'
    return clean+'\n\n'+FONT_BEGIN+'\n/* settings: '+json.dumps(metadata)+' */\n'+css+'\n'+FONT_END+'\n'


GEOMETRY_BEGIN='/* ==== ADWS Waybar arrows BEGIN ==== */'
GEOMETRY_END='/* ==== ADWS Waybar arrows END ==== */'
GEOMETRY_PATTERN=re.compile(re.escape(GEOMETRY_BEGIN)+r'.*?'+re.escape(GEOMETRY_END),re.S)

def geometry_style(original,data,root=None):
    clean=GEOMETRY_PATTERN.sub('',original).rstrip();rules=[]
    root=Path(root or Path(__file__).resolve().parents[1])
    for bar in data if isinstance(data,list) else [data]:
        modules=[m for slot in ('left','center','right') for m in bar.get('modules-'+slot,[]) if isinstance(m,str)]
        if not any(m.startswith(('custom/left_div','custom/right_div')) for m in modules):continue
        height=bar.get('height',30) or 30
        if isinstance(height,bool) or not isinstance(height,(int,float)) or not 0<height<=256:raise ValueError(_tr('无效的高度'))
        name=bar.get('name');selector='window#waybar'
        if name and re.fullmatch(r'[a-zA-Z_][\w-]*',name):selector+='.'+name
        for side in ('left','right'):
            rules.append(selector+' #custom-'+side+'_div { padding: 0; font-size: 0; min-width: '+str(max(4,height/2))+'px; background-size: 100% 100%; background-repeat: no-repeat; background-image: -gtk-recolor(url('+json.dumps(str(root/'config/waybar'/('arrow-'+side+'-symbolic.svg')))+')); }')
    if not rules:return clean+'\n'
    return clean+'\n\n'+GEOMETRY_BEGIN+'\n'+'\n'.join(rules)+'\n'+GEOMETRY_END+'\n'


def autostart_status(config, niri_path=None):
    import shlex
    if niri_path is None:
        from adws_windows import config_path
        niri_path=config_path()
    root=Path(niri_path).expanduser().resolve();seen=set();entries=[]
    def visit(path):
        path=Path(path).resolve()
        if path in seen or len(seen)>=64:return
        seen.add(path)
        if not path.is_file():return
        text=path.read_text()
        for index,row in enumerate(text.splitlines(keepends=True)):
            try:args=shlex.split(row.rstrip().rstrip(';'),comments=True)
            except ValueError:continue
            if not args or row.lstrip().startswith('//'):continue
            if args[0]=='include' and len(args)>1:
                child=Path(os.path.expandvars(args[-1])).expanduser();visit(child if child.is_absolute() else path.parent/child)
            elif len(args)>1 and args[0]=='spawn-at-startup' and Path(args[1]).name=='waybar':
                chosen=option(args[1:],'-c','--config')
                target=Path(chosen).expanduser() if chosen else default_config()
                if not target.is_absolute():target=Path.home()/target
                if target.resolve()==Path(config).resolve():entries.append((path,index))
    visit(root)
    return {'available':root.is_file(),'enabled':bool(entries),'entries':entries,'root':root}

def set_autostart(config, style, enabled, niri_path=None):
    from adws_autostart import write_config
    state=autostart_status(config,niri_path)
    if not state['available']:raise ValueError(_tr('未找到 Niri 配置。'))
    if bool(enabled)==state['enabled']:return
    if enabled:
        root=state['root'];text=root.read_text()
        line='spawn-at-startup '+' '.join(json.dumps(v,ensure_ascii=False) for v in ['waybar','-c',str(Path(config).resolve()),'-s',str(Path(style).resolve())])
        from adws_topbar import BEGIN,END
        pattern=re.compile(re.escape(BEGIN)+r'.*?'+re.escape(END),re.S)
        text=pattern.sub('',text)
        write_config(root,text.rstrip()+'\n\n'+BEGIN+'\n'+line+'\n'+END+'\n')
    else:
        changes={}
        for path,index in state['entries']:changes.setdefault(path,set()).add(index)
        originals={path:path.read_text() for path in changes};written=[]
        try:
            for path,indexes in changes.items():
                if path.read_text()!=originals[path]:raise ValueError(_tr('自启配置已被其他程序修改，请重新读取。'))
                content=''.join(row for i,row in enumerate(originals[path].splitlines(keepends=True)) if i not in indexes)
                write_config(path,content);written.append(path)
        except Exception:
            from adws_atomic import replace_files
            replace_files({path:originals[path].encode() for path in written});raise


def import_config(path):
    """Stage a JSONC source, preserving comments and resolving its includes."""
    path=Path(path).expanduser().resolve()
    if is_adws(path):raise ValueError(_tr('请使用任务栏外观设置修改 ADWS 底栏。'))
    with path.open('rb') as stream:raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024:raise ValueError(_tr('配置文件过大。'))
    text=raw.decode('utf-8-sig');data=decode(text)
    for index,bar in enumerate(data if isinstance(data,list) else [data]):
        includes=bar.get('include')
        if includes is None:continue
        values=[includes] if isinstance(includes,str) else includes
        if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise ValueError(_tr('include 必须为路径字符串或路径列表。'))
        resolved=[]
        for value in values:
            item=Path(os.path.expandvars(value)).expanduser()
            resolved.append(str(item if item.is_absolute() else path.parent/item))
        text=patch(text,index,{'include':resolved[0] if isinstance(includes,str) else resolved})
    data=decode(text)
    return {'text':text,'data':data,'catalog':module_catalog(path,data)}


def commit_bundle(config,files,backup):
    """Rollback the set if the selected bar cannot restart with new contents."""
    from adws_atomic import replace_files
    before={Path(p).resolve():Path(p).read_bytes() if Path(p).exists() else None for p in files}
    replace_files(files)
    try:reload(config)
    except Exception as error:
        replace_files({p:raw for p,raw in before.items() if raw is not None})
        for p,raw in before.items():
            if raw is None:p.unlink(missing_ok=True)
        try:reload(config)
        except Exception as recovery:raise RuntimeError(_tr('配置已回滚，但 Waybar 重启失败；备份：%s') % backup) from recovery
        raise RuntimeError(_tr('应用失败，已恢复原配置；备份：%s') % backup) from error

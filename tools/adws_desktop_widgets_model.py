"""Desktop-only instances and geometry; package discovery is shared, layouts are not."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import uuid

BUILTINS = {
    'builtin:clock': {'name': '时钟', 'icon': 'preferences-system-time-symbolic'},
    'builtin:calendar': {'name': '日历', 'icon': 'x-office-calendar-symbolic'},
    'builtin:note': {'name': '便签', 'icon': 'accessories-text-editor-symbolic'},
}
MAX_INSTANCES = 32


def layout_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/desktop-widgets.json'


def normalize(data):
    if not isinstance(data, dict) or data.get('version', 1) != 1:
        raise ValueError('Unsupported desktop widget layout')
    rows = data.get('instances', [])
    if not isinstance(rows, list) or len(rows) > MAX_INSTANCES:
        raise ValueError('Desktop widgets must be an array of at most 32 instances')
    clean, seen = [], set()
    for raw in rows:
        if not isinstance(raw, dict): raise ValueError('Invalid desktop widget')
        item = copy.deepcopy(raw)
        key = item.get('instance')
        if not isinstance(key, str) or not key.startswith('desktop-') or len(key)>100 or not all(c.isalnum() or c=='-' for c in key) or key in seen:
            raise ValueError('Invalid or duplicate desktop instance')
        seen.add(key)
        css=item.get('css','')
        if not isinstance(css,str) or len(css)>65536:raise ValueError('Widget CSS must be text up to 64 KiB')
        item['css']=css
        if not isinstance(item.get('component'), str) or len(item['component'])>256: raise ValueError('Invalid component')
        if not isinstance(item.get('monitor','primary'), str) or len(item.get('monitor','primary'))>128: raise ValueError('Invalid monitor')
        if not isinstance(item.get('settings',{}),dict): raise ValueError('Invalid widget settings')
        if len(json.dumps(item.get('settings',{}),ensure_ascii=False))>65536: raise ValueError('Widget settings too large')
        if item['component']=='builtin:note' and (not isinstance(item.get('settings',{}).get('text',''),str) or len(item.get('settings',{}).get('text',''))>20000):
            raise ValueError('Invalid desktop note')
        relative='x_percent' in item or 'y_percent' in item
        if relative:
            for field in ('x_percent','y_percent'):
                value=item.get(field)
                if type(value) not in (int,float) or not math.isfinite(value) or not -100<=value<=100:
                    raise ValueError('Widget position must be between -100% and +100%')
                item[field]=float(value)
            item.pop('x',None);item.pop('y',None)
        geometry_fields=[('width',360,200,2000),('height',220,120,1600)]
        if not relative:geometry_fields += [('x',40,0,100000),('y',40,0,100000)]
        for field,default,low,high in geometry_fields:
            value=item.get(field,default)
            if type(value) is not int: raise ValueError('Widget geometry must use integer logical pixels')
            item[field]=max(low,min(high,value))
        scope=item.get('monitor_scope','primary' if item.get('monitor','primary')=='primary' else 'screen')
        if scope not in ('screen','primary','all'):raise ValueError('Invalid desktop widget screen scope')
        item['monitor_scope']=scope
        item.update(enabled=item.get('enabled',True) is True,locked=item.get('locked',False) is True,
                    monitor=item.get('monitor','primary'),settings=item.get('settings',{}))
        clean.append(item)
    result={'version':1,'instances':clean}
    if len(json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8'))+1>3*1024*1024:raise ValueError('Widget layout too large')
    return result


def load(path=None):
    path=Path(path or layout_path())
    if not path.exists(): return normalize({})
    if path.stat().st_size>3*1024*1024: raise ValueError('Widget layout too large')
    return normalize(json.loads(path.read_text()))


def save(data,path=None):
    data=normalize(data);path=Path(path or layout_path());path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.desktop-widgets-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.write('\n')
        os.replace(tmp,path)
    finally: Path(tmp).unlink(missing_ok=True)
    return data


def catalog():
    from adws_layout import scan_available_plugins
    values=[{'key':key,**info,'kind':'builtin','repeatable':True} for key,info in BUILTINS.items()]
    values.extend({'key':e['manifest']['id'],'name':e['manifest']['name'],'kind':'plugin',
                   'icon':'application-x-addon-symbolic','repeatable':e['manifest'].get('isSingleOnly') is not True,
                   'file':e['file'],'manifest':e['manifest']} for e in scan_available_plugins('desktop') if e.get('ok'))
    # Legacy instances still resolve and retain their data. Only the new clock
    # appears in the add menu while its package is installed.
    if any(v['key']=='org.AkiACG-Community.desktopBasicPack.clock' for v in values):
        for v in values:
            if v['key']=='builtin:clock':v['selectable']=False
    return values


def add(data,definition,monitor='primary'):
    data=normalize(data)
    if len(data['instances'])>=MAX_INSTANCES: raise ValueError('最多添加 32 个桌面组件。')
    if not definition.get('repeatable',True) and any(r['component']==definition['key'] and r['enabled'] for r in data['instances']):
        raise ValueError('此桌面组件只能添加一个。')
    offset=5*(len(data['instances'])%8)
    size=definition.get('manifest',{}).get('desktopSize',[400,240])
    if not isinstance(size,list) or len(size)!=2 or any(type(v)!=int for v in size):size=[400,240]
    data['instances'].append({'instance':'desktop-'+uuid.uuid4().hex,'component':definition['key'],
                             'monitor':monitor,'x_percent':offset,'y_percent':offset,'width':size[0],'height':size[1],
                             'settings':{},'enabled':True,'locked':False})
    return normalize(data)


def geometry(row,width,height):
    width=max(1,int(width));height=max(1,int(height))
    w=min(row['width'],width);h=min(row['height'],height)
    if 'x_percent' in row and 'y_percent' in row:
        return round((row['x_percent']+100)/200*(width-w)),round((row['y_percent']+100)/200*(height-h)),w,h
    return min(row['x'],width-w),min(row['y'],height-h),w,h


def position(row,x,y,width,height):
    """Center-origin percentages of available travel, keeping the full card visible."""
    _,_,w,h=geometry(row,width,height)
    def axis(pixel,travel,previous):
        # A temporarily smaller screen must not erase a saved edge/center anchor.
        return previous if travel<=0 else max(-100.,min(100.,pixel/travel*200-100))
    return {'x_percent':axis(x,width-w,row.get('x_percent',0.)),
            'y_percent':axis(y,height-h,row.get('y_percent',0.))}


def move(row,x,y,width,height):
    row.update(position(row,x,y,width,height));row.pop('x',None);row.pop('y',None)


def percentages(row,width,height):
    if 'x_percent' in row and 'y_percent' in row:
        return {key:row[key] for key in ('x_percent','y_percent')}
    x,y,_,_=geometry(row,width,height)
    return position(row,x,y,width,height)


def visible_on(row,monitor,is_primary=False,aliases=()):
    scope=row.get('monitor_scope','primary' if row.get('monitor','primary')=='primary' else 'screen')
    return row.get('enabled',True) and (scope=='all' or (scope=='primary' and is_primary) or
        (scope=='screen' and row['monitor'] in (monitor,*aliases)))


def scope_values(scope,monitor,is_primary):
    if scope not in ('screen','primary','all'):raise ValueError('Invalid desktop widget screen scope')
    if scope=='primary' and not is_primary:raise ValueError('仅限主屏幕仅能在主屏幕选择。')
    return {'monitor_scope':scope,'monitor':'primary' if scope=='primary' else monitor}


def mutate(operation,path=None):
    """Serialize field edits from the desktop and the separate settings process."""
    import fcntl
    path=Path(path or layout_path());path.parent.mkdir(parents=True,exist_ok=True)
    with open(path.with_suffix('.lock'),'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return save(operation(load(path)),path)


def validate_instances(data,definitions):
    singles={d['key'] for d in definitions if not d.get('repeatable',True)}
    seen=set()
    for row in data['instances']:
        if row['enabled'] and row['component'] in singles:
            if row['component'] in seen:raise ValueError('此桌面组件只能添加一个。')
            seen.add(row['component'])
    return data


def duplicate(data, identity, definitions):
    data=normalize(data)
    original=next(r for r in data['instances'] if r['instance']==identity)
    definition=next(d for d in definitions if d['key']==original['component'])
    result=add(data,definition,original['monitor'])
    unique=result['instances'][-1]['instance']
    row=copy.deepcopy(original);row.update(instance=unique,locked=False,enabled=True)
    if 'x_percent' in row:
        for key in ('x_percent','y_percent'):row[key]=row[key]+5 if row[key]<=95 else row[key]-5
    else:row.update(x=min(100000,row['x']+24),y=min(100000,row['y']+24))
    result['instances'][-1]=row
    return normalize(result)

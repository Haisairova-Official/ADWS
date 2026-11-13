"""Persistent folder groups; screen movement never rewrites internal grid cells."""
import copy
import json
import math
from pathlib import Path
import uuid


def new_group(directory, monitor='primary', name=None):
    directory = str(Path(directory).expanduser().absolute())
    return {'id':uuid.uuid4().hex, 'name': name or Path(directory).name or '桌面',
            'directory':directory, 'monitor':monitor, 'x':0.04, 'y':0.06,
            'width':448, 'height':360, 'columns':4, 'icon_size':40, 'cells':{},
            'material':'mica', 'background_color':'', 'background_image':'',
            'image_fit':'cover', 'opacity':0.78}


def validate(data):
    if not isinstance(data,dict) or data.get('version') != 1 or not isinstance(data.get('groups'),list):
        raise ValueError('Invalid desktop group configuration')
    if not isinstance(data.get('default_monitor','primary'),str):
        raise ValueError('Invalid default monitor')
    ids = set()
    for row in data['groups']:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or row['id'] in ids:
            raise ValueError('Invalid or duplicate desktop group id')
        ids.add(row['id'])
        for key in ('name','directory','monitor'):
            if not isinstance(row.get(key),str) or not row[key] or len(row[key])>4096:
                raise ValueError('Invalid desktop group '+key)
        if not Path(row['directory']).is_absolute():
            raise ValueError('Group directory must be absolute')
        for key,lo,hi in [('x',0,1),('y',0,1),('width',220,2400),('height',160,2000),('columns',1,16),('icon_size',24,96)]:
            value=row.get(key)
            if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
                raise ValueError('Invalid desktop group '+key)
            if key not in ('x','y') and type(value) is not int:
                raise ValueError('Group size must be integral')
        if row.get('material','mica') not in ('mica','acrylic','candy') or row.get('image_fit','cover') not in ('cover','contain','stretch','center','tile'):
            raise ValueError('Invalid group background style')
        opacity=row.get('opacity',0.78)
        if type(opacity) not in (int,float) or not math.isfinite(opacity) or not 0<=opacity<=1:
            raise ValueError('Invalid group opacity')
        for key in ('background_color','background_image'):
            if not isinstance(row.get(key,''),str):raise ValueError('Invalid group background')
        if not isinstance(row.get('show_hidden', False), bool):
            raise ValueError('Invalid hidden file preference')
        if not isinstance(row.get('cells'),dict):
            raise ValueError('Invalid desktop grid')
        for key,cell in row['cells'].items():
            if not isinstance(key,str) or not isinstance(cell,list) or len(cell)!=2 or any(type(v)is not int or v<0 or v>100000 for v in cell):
                raise ValueError('Invalid desktop cell')
    return data


def load(path, directory, old_positions=None):
    if path.exists():
        return validate(json.loads(path.read_text()))
    row=new_group(directory)
    # Preserve one legacy per-output layout; no mirrored copies on every screen.
    layouts=old_positions or {}
    chosen=next((v for k,v in layouts.items() if k.endswith(':0') and v),{})
    for filename, cell in chosen.items():
        if Path(filename).parent == Path(directory) and isinstance(cell,(list,tuple)) and len(cell)==2 and all(type(v)is int and 0<=v<=100000 for v in cell):
            row['cells'][Path(filename).name]=list(cell)
    if row['cells']:
        row['columns']=min(16,max(row['columns'],max(c[0] for c in row['cells'].values())+1))
    return {'version':1,'default_monitor':'primary','groups':[row]}


def geometry(row, width, height):
    w,h=min(row['width'],max(1,width)),min(row['height'],max(1,height))
    return round(row['x']*max(0,width-w)),round(row['y']*max(0,height-h)),w,h


def move(row, x, y, width, height):
    _,_,w,h=geometry(row,width,height)
    row['x']=max(0,min(1,x/max(1,width-w)))
    row['y']=max(0,min(1,y/max(1,height-h)))


def grid(row, names):
    cells, used = {},set()
    for name in names:
        cell=row['cells'].get(name)
        if cell and tuple(cell) not in used:
            cells[name]=list(cell);used.add(tuple(cell))
    index = 0
    for name in names:
        if name in cells: continue
        while (index%row['columns'],index//row['columns']) in used: index+=1
        cell=[index%row['columns'],index//row['columns']]
        cells[name]=cell;used.add(tuple(cell))
    # Retain temporarily missing entries so folder remounts recover layout.
    row['cells'].update(cells)
    return cells


def arrange_visible(row, ordered_names):
    """Apply one explicit arrangement; keep off-screen and hidden file positions."""
    columns = row['columns']
    for index, name in enumerate(ordered_names):
        row['cells'][name] = [index % columns, index // columns]


def move_icon(row, name, column, line):
    target=[max(0,min(row['columns']-1,column)),max(0,line)]
    previous=row['cells'].get(name,[0,0])
    for other,cell in row['cells'].items():
        if other!=name and cell==target:
            row['cells'][other]=previous
            break
    row['cells'][name]=target

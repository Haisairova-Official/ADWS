"""Original desktopBasicPack logic. No GTK code is loaded into the desktop host."""
import copy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import socket
import tempfile
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PACKAGE='org.AkiACG-Community.desktopBasicPack'
ASSET=str(Path(__file__).resolve().parent/'assets/default.svg')

def tr(zh,en):
    locale=os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG','zh_CN')
    language=(os.environ.get('LANGUAGE') or locale).split(':')[0]
    return zh if locale.split('.')[0].upper() not in ('C','POSIX') and language.lower().startswith('zh') else en

def label(id,text,style=''):
    return dict(id=id,type='label',text=str(text),classes=style.split())

def button(id,text,action,**more):
    return dict(id=id,type='button',text=text,action=action,**more)

def box(id,children,kind='column',**more):return dict(id=id,type=kind,children=children,**more)

def collapse(line):
    packed=[v for v in line if v];result=[];score=0;i=0
    while i<len(packed):
        value=packed[i]
        if i+1<len(packed) and value==packed[i+1]:value*=2;score+=value;i+=1
        result.append(value);i+=1
    return result+[0]*(4-len(result)),score

def move_board(board,direction):
    if direction not in ('left','right','up','down'):return list(board),0
    result=list(board);score=0
    for line in range(4):
        indices=[line*4+i for i in range(4)] if direction in ('left','right') else [i*4+line for i in range(4)]
        if direction in ('right','down'):indices.reverse()
        values,points=collapse([board[i] for i in indices]);score+=points
        for i,v in zip(indices,values):result[i]=v
    return result,score

def available_moves(board):
    return any(move_board(board,d)[0]!=board for d in ('left','right','up','down'))

def puzzle_neighbors(index):
    return [i for i in range(16) if abs(i//4-index//4)+abs(i%4-index%4)==1]

def puzzle_solvable(board):
    values=[v for v in board if v!=15]
    inversions=sum(a>b for i,a in enumerate(values) for b in values[i+1:])
    return (inversions+4-board.index(15)//4)%2==1

def seconds_text(seconds):
    value=max(0,int(math.ceil(seconds)));h,remain=divmod(value,3600);m,s=divmod(remain,60)
    return f'{h:02}:{m:02}:{s:02}' if h else f'{m:02}:{s:02}'

class Engine:
    def __init__(self,kind,settings,path,now=time.time,rng=None):
        self.kind=kind;self.settings=settings;self.path=Path(path);self.now=now;self.rng=rng or random.Random();self.notice='';self.selected=None;self.preview=False
        self.state={};self.dirty=False
        try:
            if self.path.exists():
                if self.path.stat().st_size>256*1024:raise ValueError('state too large')
                value=json.loads(self.path.read_text())
                if not isinstance(value,dict) or value.get('version')!=1 or value.get('kind')!=kind:raise ValueError('invalid state')
                self.state=value
        except (OSError,ValueError):
            self.notice=tr('存档无法读取，已使用新状态。','Saved state could not be read; using a fresh state.')
        if kind=='game2048':
            b=self.state.get('board')
            if not isinstance(b,list) or len(b)!=16 or any(type(v)!=int or v<0 or v>2**30 or (v and v&(v-1)) for v in b):
                self.state={'board':[0]*16,'score':0,'best':0};self.spawn();self.spawn();self.dirty=True
            for k in ('score','best'):
                if type(self.state.get(k))!=int or not 0<=self.state[k]<=10**12:self.state[k]=0
        elif kind=='puzzle':
            b=self.state.get('board')
            if not isinstance(b,list) or len(b)!=16 or any(type(v)!=int for v in b) or sorted(b)!=list(range(16)):self.state={'board':list(range(16)),'moves':0};self.shuffle()
            # Previous releases used arbitrary swaps. Retain the image, but start a
            # solvable sliding game rather than silently loading an impossible board.
            if self.state.get('rules')!='sliding-v1' or not puzzle_solvable(self.state['board']):self.shuffle()
            if type(self.state.get('moves'))!=int or self.state['moves']<0:self.state['moves']=0
        elif kind=='timer':
            mode=settings.get('mode','countdown')
            if self.state.get('mode')!=mode:self.state={'mode':mode,'remaining':float(settings.get('minutes',25))*60,'elapsed':0.,'running':False}
            for key in ('remaining','elapsed','deadline','started'):
                value=self.state.get(key,0)
                if type(value) not in (float,int) or not math.isfinite(value) or value<0:self.state[key]=0.
            self.state['running']=self.state.get('running') is True
            minutes=float(settings.get('minutes',25))
            if not self.state['running'] and self.state.get('configured_minutes',minutes)!=minutes:self.state['remaining']=minutes*60;self.state.pop('alert',None)
            self.state['configured_minutes']=minutes
        elif kind=='note':
            if not isinstance(self.state.get('text'),str):self.state['text']=''
            self.state['text']=self.state['text'][:20000]
        if kind in ('puzzle','photo') and not isinstance(self.state.get('image',''),str):self.state['image']=''
        self.save()

    def save(self):
        self.state.update(version=1,kind=self.kind)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.widget-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as f:json.dump(self.state,f,ensure_ascii=False);f.write('\n')
            os.replace(tmp,self.path);self.dirty=False
        finally:Path(tmp).unlink(missing_ok=True)

    def spawn(self):
        empty=[i for i,v in enumerate(self.state['board']) if not v]
        if empty:self.state['board'][self.rng.choice(empty)]=4 if self.rng.random()<.1 else 2

    def shuffle(self):
        board=list(range(16))
        blank=15;previous=None
        # A random walk from the solved board preserves parity; no immediate undo.
        for _ in range(180):
            target=self.rng.choice([i for i in puzzle_neighbors(blank) if i!=previous])
            board[blank],board[target]=board[target],board[blank];previous,blank=blank,target
        if board==list(range(16)):
            target=puzzle_neighbors(blank)[0];board[blank],board[target]=board[target],board[blank]
        self.state.update(board=board,moves=0,rules='sliding-v1');self.selected=None;self.preview=False;self.dirty=True

    def timer_value(self):
        s=self.state;now=self.now()
        if s['mode']=='stopwatch':return s.get('elapsed',0)+(max(0,now-s.get('started',now)) if s['running'] else 0)
        return max(0,s.get('deadline',now)-now) if s['running'] else s.get('remaining',0)

    def event(self,event):
        if not isinstance(event,dict) or not isinstance(event.get('action'),str):return
        action=event['action'];value=event.get('value');s=self.state
        if action=='alert_seen' and value==s.get('alert'):s['alert_seen']=value;self.dirty=True
        if self.kind=='game2048':
            if action in ('left','right','up','down'):
                board,points=move_board(s['board'],action)
                if board!=s['board']:
                    s['undo']={'board':list(s['board']),'score':s['score']};s['board']=board;s['score']+=points;s['best']=max(s['best'],s['score']);self.spawn();self.dirty=True
            elif action=='new':
                s.update(board=[0]*16,score=0);s.pop('undo',None);self.spawn();self.spawn();self.dirty=True
            elif action=='undo' and isinstance(s.get('undo'),dict):
                old=s.pop('undo');b=old.get('board');score=old.get('score')
                if isinstance(b,list) and len(b)==16 and all(type(v)==int and 0<=v<=2**30 and (not v or not v&(v-1)) for v in b) and type(score)==int and score>=0:s.update(board=b,score=score);self.dirty=True
        elif self.kind=='timer':
            if action=='toggle':
                v=self.timer_value()
                if s['running']:
                    s['elapsed' if s['mode']=='stopwatch' else 'remaining']=v;s['running']=False
                else:
                    if s['mode']=='stopwatch':s['started']=self.now()
                    else:
                        if v<=0:v=float(self.settings.get('minutes',25))*60
                        s['remaining']=v;s['deadline']=self.now()+v
                    s['running']=True;s.pop('alert',None)
                self.dirty=True
            elif action=='reset':
                s.update(running=False,remaining=float(self.settings.get('minutes',25))*60,elapsed=0.);s.pop('alert',None);self.dirty=True
            elif action=='minute' and s['mode']=='countdown':
                s['remaining']=min(86400,self.timer_value()+60)
                if s['running']:s['deadline']=self.now()+s['remaining']
                s.pop('alert',None);self.dirty=True
        elif self.kind=='puzzle':
            if action=='shuffle':self.shuffle()
            elif action=='preview':self.preview=not self.preview;self.selected=None
            elif re.fullmatch(r'tile_(?:[0-9]|1[0-5])',action) and not self.preview:
                index=int(action[5:])
                blank=s['board'].index(15)
                if index in puzzle_neighbors(blank):
                    s['board'][blank],s['board'][index]=s['board'][index],s['board'][blank]
                    s['moves']+=1;self.dirty=True
        elif self.kind=='note' and action=='edit' and isinstance(value,str):s['text']=value[:20000];self.dirty=True
        if self.kind in ('puzzle','photo'):
            if action=='image' and isinstance(value,str) and len(value)<4096:
                path=Path(value).expanduser()
                if path.is_file() and path.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.bmp','.gif','.svg'):
                    s['image']=str(path.resolve());self.dirty=True
                    if self.kind=='puzzle':self.shuffle()
            elif action=='default':s['image']='';self.dirty=True
        if self.dirty:self.save()

    def render(self):
        s=self.state;kind=self.kind;alert=None;keys={}
        if kind=='clock':
            try:zone=ZoneInfo(self.settings['timezone']) if self.settings.get('timezone') else None
            except (ZoneInfoNotFoundError,ValueError):zone=None;self.notice=tr('时区无效，使用系统时间。','Invalid timezone; using system time.')
            now=datetime.fromtimestamp(self.now(),zone);hour='%H' if self.settings.get('hour24',True) else '%I'
            pattern=hour+':%M'+(':%S' if self.settings.get('seconds',True) else '')
            weekdays=['星期一','星期二','星期三','星期四','星期五','星期六','星期日']
            zone_label=label('zone',self.settings.get('timezone') or tr('本地时间','Local time'),'basic-eyebrow')
            date=label('date',now.strftime('%Y-%m-%d')+' · '+tr(weekdays[now.weekday()],now.strftime('%A')),'basic-muted')
            if self.settings.get('display')=='analog':
                aware=now if now.tzinfo else now.astimezone()
                face=self.settings.get('face','retro')
                if face not in ('retro','minimal','railway','orbit'):face='retro'
                children=[dict(id='dial',type='clockface',face=face,seconds=self.settings.get('second_hand',True),utc_offset=int(aware.utcoffset().total_seconds()),path=self.settings.get('face_image',''),markers=self.settings.get('dial_markers',True))]
            else:
                children=[zone_label,label('time',now.strftime(pattern),'basic-clock'),date]
                if not self.settings.get('hour24',True):children.append(label('period',now.strftime('%p'),'basic-eyebrow'))
        elif kind=='timer':
            value=self.timer_value();running=s['running'];stopwatch=s['mode']=='stopwatch'
            if not stopwatch and running and value<=0:
                s.update(running=False,remaining=0,alert=str(self.now()));self.save();running=False
            if s.get('alert') and s.get('alert_seen')!=s.get('alert'):alert={'id':s['alert'],'text':tr('计时结束','Timer finished')}
            children=[label('mode',tr('秒表','Stopwatch') if stopwatch else tr('倒计时','Countdown'),'basic-eyebrow'),label('time',seconds_text(value),'basic-clock'),label('status',tr('计时结束','Finished') if s.get('alert') else tr('正在计时','Running') if running else tr('已暂停','Paused'),'basic-muted'),box('actions',[button('toggle',tr('暂停','Pause') if running else tr('开始','Start'),'toggle',classes=['basic-accent']),button('reset',tr('重置','Reset'),'reset')],'row')]
            if not stopwatch:children.extend([dict(id='progress',type='progress',value=max(0,min(1,value/max(1,float(self.settings.get('minutes',25))*60)))),button('minute',tr('增加一分钟','Add a minute'),'minute')])
        elif kind=='game2048':
            board=s['board'];done=not available_moves(board);won=max(board)>=2048
            children=[box('scores',[label('score',tr('得分 ','Score ')+str(s['score']),'basic-eyebrow'),label('best',tr('最高 ','Best ')+str(s['best']),'basic-muted')],'row'),box('board',[label('cell'+str(i),str(v) if v else '',f'basic-tile tile-{min(v,2048)}') for i,v in enumerate(board)],'grid',columns=4),label('status',tr('无路可走，试试撤销或新开一局。','No moves left. Undo or start again.') if done else tr('已达成 2048，可以继续挑战。','2048 reached. Keep going!') if won else tr('点击棋盘后使用方向键，或点击下方按钮。','Click the board and use arrow keys or the buttons below.'),'basic-muted'),box('directions',[button(d,symbol,d) for d,symbol in [('left','←'),('up','↑'),('down','↓'),('right','→')]],'row'),box('actions',[button('undo',tr('撤销','Undo'),'undo',enabled=bool(s.get('undo'))),button('new',tr('新游戏','New game'),'new',confirm=tr('重新开始本局？','Start a new game?'))],'row')]
            keys={'Left':'left','Right':'right','Up':'up','Down':'down'}
        elif kind=='puzzle':
            image=s.get('image') or ASSET;board=list(range(16)) if self.preview else s['board']
            tiles=[];blank=s['board'].index(15)
            for i,v in enumerate(board):
                # Keep the image node shape stable when the empty cell moves.
                tiles.append(button('tile'+str(i),'','tile_'+str(i),classes=['basic-puzzle-tile']+(['basic-empty'] if v==15 and not self.preview else []),enabled=not self.preview and i in puzzle_neighbors(blank),children=[dict(id='image'+str(i),type='image',path=image,crop=[v%4,v//4,4,4],size=52,fit='cover',classes=['basic-hidden-image'] if v==15 and not self.preview else [])]))
            children=[label('moves',tr('移动次数：','Moves: ')+str(s['moves']),'basic-eyebrow'),box('board',tiles,'grid',columns=4),label('status',tr('完成！','Completed!') if s['board']==list(range(16)) else tr('将相邻图片滑入空位','Slide a neighboring tile into the gap'),'basic-muted'),box('actions',[button('preview',tr('继续拼图','Continue') if self.preview else tr('查看原图','View original'),'preview'),button('shuffle',tr('打乱','Shuffle'),'shuffle',confirm=tr('打乱并重新开始？','Shuffle and start again?'))],'row'),dict(id='choose',type='file',action='image',text=tr('选择图片','Choose image'))]
        elif kind=='photo':
            children=[dict(id='photo',type='image',path=s.get('image') or ASSET,size=int(self.settings.get('image_size',190)),fit=self.settings.get('fit','contain')),label('caption',self.settings.get('caption',''),'basic-muted'),box('actions',[dict(id='choose',type='file',action='image',text=tr('选择图片','Choose image')),button('default',tr('恢复示例','Use sample'),'default')],'row')]
        else:
            children=[label('heading',self.settings.get('title') or tr('随手记','Quick note'),'basic-eyebrow'),dict(id='note',type='text',action='edit',value=s.get('text',''),placeholder=tr('写点什么…','Write something…')),label('saved',tr('自动保存 · 每张便签独立存储','Autosaved · Stored separately for each note'),'basic-muted')]
        if self.notice:children.append(label('notice',self.notice,'basic-warning'))
        return dict(text=kind,primary=kind,view=box('root',children),key_actions=keys,alert=alert)

def run(kind):
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--settings-json',default='{}');parser.add_argument('--output-json',action='store_true');parser.add_argument('--once',action='store_true');args=parser.parse_args()
    settings=json.loads(args.settings_json)
    if not isinstance(settings,dict):raise ValueError('settings must be an object')
    instance=os.environ.get('ADWS_PLUGIN_INSTANCE','preview-'+kind)
    if not re.fullmatch('[A-Za-z0-9_.-]{1,128}',instance):raise ValueError('invalid instance ID')
    path=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/desktop-plugins'/PACKAGE/(instance+'.json')
    engine=Engine(kind,settings,path)
    if args.once:print(json.dumps(engine.render(),ensure_ascii=False));return
    address=os.environ.get('ADWS_DESKTOP_EVENT_SOCKET');channel=None;stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    if address:
        channel=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);channel.settimeout(.25)
        Path(address).unlink(missing_ok=True);channel.bind(address);os.chmod(address,0o600)
    last=None;heartbeat=0
    try:
        while not stopped:
            payload=engine.render();encoded=json.dumps(payload,ensure_ascii=False)
            if encoded!=last or time.monotonic()-heartbeat>=5:
                print(encoded,flush=True);last=encoded;heartbeat=time.monotonic()
            if channel:
                try:
                    raw=channel.recv(128*1024+1)
                    if len(raw)<=128*1024:engine.event(json.loads(raw))
                except socket.timeout:pass
                except (ValueError,UnicodeError):pass
            else:time.sleep(.25)
    finally:
        if engine.dirty:engine.save()
        if channel:channel.close();Path(address).unlink(missing_ok=True)

"""Local agenda storage with validated dates and atomic updates."""
from datetime import date
import json
import os
from pathlib import Path
import re
import uuid
from adws_atomic import replace_files
from adws_i18n import tr


def agenda_path():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'adws/agenda.json'


def validate_event(raw):
    if not isinstance(raw,dict): raise ValueError(tr('日程格式无效。'))
    day=str(raw.get('date',''))
    try: parsed=date.fromisoformat(day)
    except ValueError: raise ValueError(tr('日期格式应为 YYYY-MM-DD。')) from None
    if parsed.isoformat()!=day: raise ValueError(tr('日期格式应为 YYYY-MM-DD。'))
    title=str(raw.get('title','')).strip()
    if not title or len(title)>240: raise ValueError(tr('请填写日程名称，最多 240 个字符。'))
    start=str(raw.get('time','')).strip(); end=str(raw.get('end','')).strip()
    for value in (start,end):
        if value and not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):
            raise ValueError(tr('时间格式应为 HH:mm，全天日程请留空。'))
    if end and (not start or end<=start): raise ValueError(tr('结束时间必须晚于开始时间。'))
    notes=str(raw.get('notes','')).strip()
    if len(notes)>2000: raise ValueError(tr('日程备注最多 2000 个字符。'))
    identity=str(raw.get('id') or uuid.uuid4())
    try: uuid.UUID(identity)
    except ValueError: raise ValueError(tr('日程编号无效。')) from None
    return {'id':identity,'date':day,'title':title,'time':start,'end':end,'notes':notes}


def load_events(path=None):
    path=agenda_path() if path is None else Path(path)
    try:
        if path.stat().st_size>4*1024*1024: raise ValueError(tr('日程文件过大。'))
        data=json.loads(path.read_text())
    except FileNotFoundError: return []
    if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('events'),list):
        raise ValueError(tr('日程文件格式无效，原文件已保留。'))
    if len(data['events'])>5000: raise ValueError(tr('日程数量过多。'))
    if any(not isinstance(item,dict) or not item.get('id') for item in data['events']):
        raise ValueError(tr('日程编号无效。'))
    events=[validate_event(item) for item in data['events']]
    if len({item['id'] for item in events})!=len(events): raise ValueError(tr('日程编号重复，原文件已保留。'))
    return sorted(events,key=lambda item:(item['date'],item['time'],item['title']))


def save_event(raw,path=None):
    path=agenda_path() if path is None else Path(path)
    event=validate_event(raw); events=load_events(path)
    current=next((i for i,item in enumerate(events) if item['id']==event['id']),None)
    if current is None:
        if len(events)>=5000: raise ValueError(tr('日程数量过多。'))
        events.append(event)
    else: events[current]=event
    write_events(events,path); return event


def delete_event(identity,path=None):
    path=agenda_path() if path is None else Path(path)
    events=load_events(path)
    write_events([item for item in events if item['id']!=identity],path)


def write_events(events,path):
    payload=json.dumps({'version':1,'events':events},ensure_ascii=False,indent=2).encode()
    replace_files({path:payload})
    path.chmod(0o600)

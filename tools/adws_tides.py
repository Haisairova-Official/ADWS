"""Free model sea-level outlook, kept distinct from observed harbour tides."""
from datetime import datetime,timezone
import math
import threading
import time
import urllib.parse
from gi.repository import Gtk,GLib
from adws_i18n import tr
from adws_system_settings import label,card
from adws_location import coordinates,json_request,city_location
from adws_ocean import OceanSurface


def distance_km(a,b):
    lat1,lon1=map(math.radians,a);lat2,lon2=map(math.radians,b)
    value=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(max(0,value))))


class MarineUnavailable(ValueError):
    pass


def parse_marine(data,location,now=None):
    now=time.time() if now is None else now
    lat,lon=coordinates(data['latitude'],data['longitude'])
    distance=distance_km((location['latitude'],location['longitude']),(lat,lon))
    if distance>50:raise MarineUnavailable(tr('附近没有可用海洋网格。'))
    hourly=data.get('hourly',{});times=hourly.get('time',[]);levels=hourly.get('sea_level_height_msl',[])
    samples=[]
    for stamp,height in list(zip(times,levels))[:96]:
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or not now-3600<=stamp<=now+48*3600:continue
        valid=type(height) in (int,float) and math.isfinite(height) and abs(height)<30
        samples.append((stamp,float(height) if valid else None))
    if sum(height is not None for _,height in samples)<6:raise MarineUnavailable(tr('此位置暂无有效潮位数据。'))
    peaks=[]
    for before,current,after in zip(samples,samples[1:],samples[2:]):
        if any(h is None for _,h in (before,current,after)) or after[0]-before[0]>7200:continue
        if current[0]<now:continue
        if current[1]>before[1] and current[1]>after[1]:kind='预计高点'
        elif current[1]<before[1] and current[1]<after[1]:kind='预计低点'
        else:continue
        peaks.append({'time':current[0],'height':current[1],'kind':kind})
    offset=data.get('utc_offset_seconds',0)
    if type(offset) not in (int,float) or not math.isfinite(offset) or abs(offset)>86400:offset=0
    return {'samples':samples,'peaks':peaks[:8],'offset':offset,'timezone':str(data.get('timezone','UTC'))[:80],
            'distance':distance,'updated':now,'location':dict(location),'latitude':lat,'longitude':lon}


def nearby_points(latitude,longitude):
    """Bounded search rings, including date-line and polar locations."""
    lat,lon=map(math.radians,coordinates(latitude,longitude));points=[]
    for radius in (15,30,45):
        angle=radius/6371
        for bearing in range(0,360,45):
            bearing=math.radians(bearing)
            target_lat=math.asin(max(-1,min(1,math.sin(lat)*math.cos(angle)+math.cos(lat)*math.sin(angle)*math.cos(bearing))))
            target_lon=lon+math.atan2(math.sin(bearing)*math.sin(angle)*math.cos(lat),math.cos(angle)-math.sin(lat)*math.sin(target_lat))
            points.append(coordinates(math.degrees(target_lat),(math.degrees(target_lon)+180)%360-180))
    return points


def marine_request(points):
    query=urllib.parse.urlencode({'latitude':','.join(str(p[0]) for p in points),
        'longitude':','.join(str(p[1]) for p in points),'hourly':'sea_level_height_msl',
        'forecast_days':3,'timezone':'auto','timeformat':'unixtime','cell_selection':'sea'})
    return json_request('https://marine-api.open-meteo.com/v1/marine?'+query)


def marine(location):
    lat,lon=coordinates(location['latitude'],location['longitude'])
    # Network/service errors are not evidence of a missing coast: do not fan out retries.
    initial=marine_request([(lat,lon)])
    try:return parse_marine(initial,location)
    except MarineUnavailable:pass
    # One batch only. Validate actual returned grid distances against the original
    # city, not the search points, so inland cities cannot borrow distant seas.
    payload=marine_request(nearby_points(lat,lon))
    if not isinstance(payload,list):raise ValueError('Invalid marine batch response')
    candidates=[]
    for item in payload[:24]:
        try:result=parse_marine(item,location)
        except (ValueError,TypeError,KeyError):continue
        candidates.append(result)
    if not candidates:raise MarineUnavailable(tr('附近 50 公里内暂无有效潮位数据。'))
    result=min(candidates,key=lambda item:item['distance']);result['nearby']=True
    return result


class TideCard:
    def __init__(self,host):
        self.host=host;self.location=None;self.city='';self.initial_load=False;self.generation=0;self.closed=False;self.data=None;self.busy=False
        self.box=card('潮汐趋势');self.status=label('未获取位置；自动潮汐暂不可用。','dim-label')
        self.status.set_max_width_chars(42);self.box.pack_start(self.status,False,False,0)
        self.content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);self.content.set_sensitive(False)
        self.content.pack_start(label('—','weather-temperature'),False,False,0);self.box.pack_start(self.content,False,False,0)
        self.refresh=Gtk.Button(label=tr('更新潮汐'));self.refresh.set_sensitive(False);self.refresh.connect('clicked',lambda *_:self.fetch())
        self.box.pack_start(self.refresh,False,False,0)
        source=Gtk.LinkButton.new_with_label('https://open-meteo.com/en/docs/marine-weather-api','Open-Meteo / GeoNames · CC BY 4.0')
        source.set_halign(Gtk.Align.START);self.box.pack_start(source,False,False,0)
        note=label('含潮汐影响的海面高度模型，基于平均海平面；非港口实测潮汐表，不用于航海。','dim-label');note.set_max_width_chars(42)
        self.box.pack_start(note,False,False,0);self.box.connect('destroy',self.dispose)
        self.box.connect('map',self.mapped)

    def dispose(self,*_):self.closed=True;self.generation+=1

    def mapped(self,*_):
        if self.initial_load:
            self.initial_load=False;self.fetch()

    def set_city(self,city,fetch=True):
        self.set_location(None)
        self.city=str(city).strip();self.refresh.set_sensitive(bool(self.city))
        self.initial_load=bool(self.city) and not fetch
        if self.city:
            self.status.set_text(self.city+' · '+tr('按指定城市查询潮汐'))
            if fetch:self.fetch()

    def set_location(self,location):
        self.city='';self.initial_load=False
        self.generation+=1;self.location=location;self.data=None;self.busy=False
        for child in self.content.get_children():child.destroy()
        self.content.pack_start(label('—','weather-temperature'),False,False,0);self.content.show_all();self.content.set_sensitive(False)
        self.refresh.set_sensitive(bool(location));self.status.set_text(tr('点击更新潮汐') if location else tr('未获取位置；自动潮汐暂不可用。'))
        # Location consent also describes its use for this explicitly requested forecast.
        if location:self.fetch()

    def fetch(self):
        if not (self.location or self.city) or self.busy or self.closed:return
        token=self.generation;location=dict(self.location) if self.location else None;city=self.city;self.busy=True;self.refresh.set_sensitive(False)
        self.status.set_text(tr('正在读取潮汐…'))
        def worker():
            try:
                resolved=location or city_location(city)
                if self.closed or token!=self.generation:return
                data=marine(resolved);error=None
            except MarineUnavailable as exc:data=None;error=str(exc)
            except Exception:data=None;error=tr('此位置暂无可用潮汐数据，或服务暂时不可达。')
            def done():
                if self.closed or self.host.closed or token!=self.generation:return False
                self.busy=False;self.refresh.set_sensitive(True)
                if data:self.location=resolved;self.data=data;self.render(data)
                else:self.status.set_text(error+(' · '+tr('保留上次结果') if self.data else ''))
                return False
            if not self.closed:GLib.idle_add(done)
        threading.Thread(target=worker,name='adws-tides',daemon=True).start()

    def render(self,data):
        self.status.set_text(data['location']['name']+' · '+tr('附近网格模型估算' if data.get('nearby') else '模型估算')+' · '+data['timezone'])
        for child in self.content.get_children():child.destroy()
        self.ocean=OceanSurface(self.host,data);self.content.pack_start(self.ocean,False,False,0)
        values=[h for _,h in data['samples'] if h is not None]
        self.content.pack_start(label(tr('未来两天：%s 至 %s 米')%(f'{min(values):.2f}',f'{max(values):.2f}'),'dim-label'),False,False,0)
        def display_time(stamp):return datetime.fromtimestamp(stamp+data['offset'],timezone.utc).strftime('%m/%d %H:%M')
        self.content.pack_start(label(display_time(data['samples'][0][0])+' — '+display_time(data['samples'][-1][0]),'dim-label'),False,False,0)
        for peak in data['peaks'][:4]:
            row=Gtk.Box(spacing=10);row.pack_start(label(display_time(peak['time'])+' · '+tr(peak['kind'])),True,True,0)
            row.pack_end(label(f"{peak['height']:.2f} m"),False,False,0);self.content.pack_start(row,False,False,0)
        if not data['peaks']:self.content.pack_start(label('当前时段未识别出高低点。','dim-label'),False,False,0)
        self.content.pack_start(label(tr('模型网格距查询位置约 %s 公里')%f"{data['distance']:.1f}",'dim-label'),False,False,0)
        position=label(tr('数据网格坐标：%s，%s')%(f"{data['latitude']:.4f}",f"{data['longitude']:.4f}"),'dim-label');position.set_max_width_chars(42)
        self.content.pack_start(position,False,False,0)
        self.content.pack_start(label(tr('更新时间')+' '+datetime.fromtimestamp(data['updated']).strftime('%m/%d %H:%M'),'dim-label'),False,False,0)
        self.content.set_sensitive(True);self.content.show_all()

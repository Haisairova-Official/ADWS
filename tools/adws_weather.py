"""Bounded weather presentation model and theme-native cards."""
from datetime import datetime, date
import math
import re
import cairo
from gi.repository import Gtk, Pango
from adws_i18n import tr, chinese
from adws_system_settings import label


def text(value):return str(value or '')[:120]

def number(value):
    try:
        n=float(value)
        return f'{n:g}' if math.isfinite(n) and abs(n)<100000 else '—'
    except (TypeError,ValueError):return '—'

CONDITIONS={'Overcast':'阴天','Partly cloudy':'局部多云','Cloudy':'多云','Sunny':'晴','Clear':'晴朗','Mist':'薄雾','Fog':'雾','Light rain':'小雨','Moderate rain':'中雨','Heavy rain':'大雨','Patchy rain nearby':'附近有零星降雨','Patchy rain possible':'可能有零星降雨','Light drizzle':'毛毛雨','Light snow':'小雪','Moderate snow':'中雪','Heavy snow':'大雪'}

def description(item,local=True):
    values=(item.get('lang_zh') if local and chinese() else None) or item.get('weatherDesc',[])
    result=text(values[0].get('value','')) if values and isinstance(values[0],dict) else ''
    return CONDITIONS.get(result,result) if local and chinese() else result

def icon(item):
    description_=description(item,local=False).casefold()
    for words,name in [(('thunder',),'storm'),(('snow','sleet','ice','blizzard'),'snow'),(('rain','drizzle','shower'),'showers'),(('fog','mist'),'fog'),(('overcast',),'overcast'),(('cloud',),'few-clouds')]:
        if any(word in description_ for word in words):return 'weather-'+name+'-symbolic'
    return 'weather-clear-symbolic' if any(word in description_ for word in ('sunny','clear')) else 'weather-few-clouds-symbolic'

def condition(item):
    return {'temperature':number(item.get('temp_C',item.get('tempC'))),'feels':number(item.get('FeelsLikeC')),
            'humidity':number(item.get('humidity')),'wind':number(item.get('windspeedKmph')),
            'direction':text(item.get('winddir16Point')),'gust':number(item.get('WindGustKmph')),'cloud':number(item.get('cloudcover')),
            'uv':number(item.get('uvIndex')),'visibility':number(item.get('visibility')),'pressure':number(item.get('pressure')),'precipitation':number(item.get('precipMM')),'rain':number(item.get('chanceofrain')),'description':description(item),'icon':icon(item)}

def clock_time(value):
    # Providers use English AM/PM even when the desktop's LC_TIME is Chinese.
    match=re.fullmatch(r'(\d{1,2}):(\d{2})(?:\s*(AM|PM))?',str(value or '').strip(),re.I)
    if not match:return '—'
    hour,minute=int(match[1]),int(match[2]);suffix=(match[3] or '').upper()
    if minute>59 or (suffix and not 1<=hour<=12) or (not suffix and hour>23):return '—'
    if suffix:hour=hour%12+(12 if suffix=='PM' else 0)
    return f'{hour:02d}:{minute:02d}'


def observed_time(value,fallback):
    try:
        day,raw=str(value).split(' ',1);clock=clock_time(raw)
        return datetime.fromisoformat(day+'T'+clock) if clock!='—' else fallback
    except (TypeError,ValueError):return fallback


def astronomy(day):
    raw=day.get('astronomy',[])
    raw=raw[0] if isinstance(raw,list) and raw and isinstance(raw[0],dict) else {}
    result={key:clock_time(raw.get(key)) for key in ('sunrise','sunset','moonrise','moonset')}
    result.update(phase=text(raw.get('moon_phase')),illumination=number(raw.get('moon_illumination')),date=day.get('date',''))
    try:
        sunrise=datetime.strptime(result['sunrise'],'%H:%M');sunset=datetime.strptime(result['sunset'],'%H:%M')
        minutes=int((sunset-sunrise).total_seconds()/60)
        result['daylight']=minutes if 0<minutes<1440 else None
    except ValueError:result['daylight']=None
    return result


def parse_weather(data,city,now=None):
    now=now or datetime.now()
    observed=data['current_condition'][0]
    forecast_now=observed_time(observed.get('localObsDateTime'),now)
    current=condition(observed);days=[];hours=[]
    for day in data.get('weather',[])[:3]:
        parsed=date.fromisoformat(day['date'])
        hourly=day.get('hourly',[])[:8]
        representative=next((h for h in hourly if str(h.get('time'))=='1200'),next(iter(hourly),{}))
        days.append({'date':parsed.isoformat(),'low':number(day.get('mintempC')),'high':number(day.get('maxtempC')),**{'icon':icon(representative),'description':description(representative)}})
        for item in hourly:
            try:hour=int(item['time'])//100;stamp=datetime.combine(parsed,datetime.min.time()).replace(hour=hour)
            except (ValueError,KeyError,TypeError):continue
            if stamp>=forecast_now and len(hours)<6:hours.append({'time':stamp.isoformat(),**condition(item)})
    daily=next((day for day in data.get('weather',[])[:3] if day.get('date')==forecast_now.date().isoformat()),{})
    return {'astronomy':astronomy(daily),'local_observed':forecast_now.isoformat(),'version':1,'city':text(city),'updated':now.isoformat(timespec='seconds'),'current':current,'days':days,'hours':hours}


def wind_direction(value):
    directions={'N':'北风','NNE':'北东北风','NE':'东北风','ENE':'东东北风','E':'东风','ESE':'东东南风','SE':'东南风','SSE':'南东南风','S':'南风','SSW':'南西南风','SW':'西南风','WSW':'西西南风','W':'西风','WNW':'西西北风','NW':'西北风','NNW':'北西北风'}
    return tr(directions[value]) if value in directions else value or '—'


class ForecastChart(Gtk.DrawingArea):
    """Temperature curve and probability bars; paints only when GTK needs a redraw."""
    def __init__(self,hours):
        super().__init__();self.hours=hours;self.set_size_request(-1,120)
        self.get_style_context().add_class('weather-condition');self.connect('draw',self.draw_chart)
        self.set_tooltip_text(tr('实线：温度 · 柱形：降雨概率（0–100%）'))

    def draw_chart(self,_,cr):
        from adws_ocean import monotone_segments
        width,height=self.get_allocated_width(),self.get_allocated_height()
        color=self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        def numeric(value):
            try:
                value=float(value);return value if math.isfinite(value) else None
            except (ValueError,TypeError):return None
        values=[numeric(item.get('temperature')) for item in self.hours]
        valid=[v for v in values if v is not None]
        if not valid:return False
        low,high=min(valid),max(valid);span=max(2,high-low)
        cr.save();cr.rectangle(0,0,width,height);cr.clip()
        step=width/max(1,len(values));runs=[];run=[]
        for i,(item,value) in enumerate(zip(self.hours,values)):
            x=step*(i+.5);rain=numeric(item.get('rain'))
            if rain is not None:
                bar=max(0,min(100,rain))/100*38
                cr.set_source_rgba(color.red,color.green,color.blue,.22)
                cr.rectangle(x-9,height-6-bar,18,bar);cr.fill()
            if value is None:
                if run:runs.append(run);run=[]
                continue
            run.append((x,18+(high-value)/span*52))
        if run:runs.append(run)
        for points in runs:
            cr.new_path();cr.move_to(*points[0])
            for _,c1,c2,end in monotone_segments(points):cr.curve_to(*c1,*c2,*end)
            cr.set_source_rgba(color.red,color.green,color.blue,.95);cr.set_line_width(2.5);cr.stroke()
            for x,y in points:cr.arc(x,y,3,0,math.tau);cr.fill()
        cr.restore();return False


class WeatherView(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        self.get_style_context().add_class('weather-view')
        self.hour_grid=None;self.hour_tiles=[];self.hour_columns=3
        self.connect('size-allocate',self.reflow_hours)
        self.empty()

    def reflow_hours(self,_,allocation):
        columns=6 if allocation.width>=430 else 3
        if self.hour_grid is None or columns==self.hour_columns:return
        self.hour_columns=columns
        for tile in self.hour_tiles:self.hour_grid.remove(tile)
        for i,tile in enumerate(self.hour_tiles):self.hour_grid.attach(tile,i%columns,i//columns,1,1)
        self.hour_grid.show_all()

    def clear(self):
        self.hour_grid=None;self.hour_tiles=[];self.hour_columns=3
        for child in self.get_children():child.destroy()

    def empty(self,legacy=None):
        self.clear();image=Gtk.Image.new_from_icon_name('weather-few-clouds-symbolic',Gtk.IconSize.DIALOG);image.set_pixel_size(64)
        self.pack_start(image,False,False,16)
        self.pack_start(label('选择一座城市，看看窗外的天气。','weather-summary'),False,False,0)
        if legacy:self.pack_start(label(str(legacy)[:1500],'dim-label'),False,False,0)

    @staticmethod
    def image(name,size):
        image=Gtk.Image.new_from_icon_name(name,Gtk.IconSize.DIALOG);image.set_pixel_size(size);return image

    def detail_grid(self,items):
        grid=Gtk.Grid(column_homogeneous=True,column_spacing=10,row_spacing=8)
        for i,(title,value) in enumerate(items):
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);box.get_style_context().add_class('weather-tile')
            box.pack_start(label(title,'dim-label'),False,False,0);box.pack_start(label(value,'weather-summary'),False,False,0)
            grid.attach(box,i%2,i//2,1,1)
        self.pack_start(grid,False,False,0)

    def display(self,data):
        self.clear();current=data['current'];hero=Gtk.Box(spacing=18,margin_top=12,margin_bottom=12)
        hero.get_style_context().add_class('weather-hero')
        titles=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        city=label(data['city'],'weather-city');city.set_max_width_chars(22);city.set_ellipsize(Pango.EllipsizeMode.END)
        titles.pack_start(city,False,False,0)
        titles.pack_start(label(current['temperature']+'°','weather-temperature'),False,False,0)
        titles.pack_start(label(tr(current['description']),'weather-summary'),False,False,0)
        titles.pack_start(label(tr('体感')+' '+current['feels']+' °C','dim-label'),False,False,0)
        hero.pack_start(titles,True,True,0);symbol=self.image(current['icon'],80)
        symbol.get_style_context().add_class('weather-condition');hero.pack_end(symbol,False,False,12)
        self.pack_start(hero,False,False,0)
        today=next((item for item in data['days'] if item['date']==data.get('local_observed','')[:10]),None)
        if today:
            titles.pack_start(label(tr('今日 %s° / %s°')%(today['low'],today['high']),'weather-summary'),False,False,2)
        if data['hours']:
            self.pack_start(label('接下来几小时','settings-section-title'),False,False,4)
            hours=Gtk.Grid(column_homogeneous=True,column_spacing=5,row_spacing=6);self.hour_grid=hours
            for i,item in enumerate(data['hours']):
                box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);box.get_style_context().add_class('weather-tile')
                stamp=datetime.fromisoformat(item['time']);title=Gtk.Label(label=stamp.strftime('%H:%M'));title.get_style_context().add_class('dim-label')
                box.pack_start(title,False,False,0);box.pack_start(self.image(item['icon'],24),False,False,0)
                box.pack_start(Gtk.Label(label=item['temperature']+'°'),False,False,0)
                chance=Gtk.Label(label=item.get('rain','—')+'%');chance.get_style_context().add_class('weather-condition')
                box.pack_start(chance,False,False,0)
                box.set_tooltip_text(stamp.strftime('%x %H:%M')+' · '+tr(item['description'])+'\n'+tr('降雨概率')+' '+item['rain']+'%')
                hours.attach(box,i%3,i//3,1,1);self.hour_tiles.append(box)
            self.pack_start(hours,False,False,0)
            self.pack_start(ForecastChart(data['hours']),False,False,0)
            self.pack_start(label('实线：温度 · 柱形：降雨概率（0–100%）','dim-label'),False,False,0)
        self.detail_grid([('湿度',current['humidity']+'%'),('风向与风速',wind_direction(current.get('direction',''))+' · '+current['wind']+' km/h'),
                          ('紫外线指数',current.get('uv','—')),('能见度',current.get('visibility','—')+' km'),
                          ('气压',current.get('pressure','—')+' hPa'),('降水量',current.get('precipitation','—')+' mm'),
                          ('阵风',current.get('gust','—')+' km/h'),('云量',current.get('cloud','—')+'%')])
        self.pack_start(label('未来三天','settings-section-title'),False,False,4)
        for item in data['days']:
            row=Gtk.Box(spacing=12);row.get_style_context().add_class('weather-forecast-row')
            day=date.fromisoformat(item['date']);title=tr('今天') if day==date.today() else (day.strftime('%m/%d')+' 周'+'一二三四五六日'[day.weekday()] if chinese() else day.strftime('%a %m/%d'))
            row.pack_start(label(title),True,True,0);row.pack_start(self.image(item['icon'],24),False,False,0)
            row.pack_end(label(item['low']+'°  /  '+item['high']+'°','weather-summary'),False,False,0)
            row.set_tooltip_text(tr(item['description']));self.pack_start(row,False,False,0)
        sky=data.get('astronomy',{})
        self.pack_start(label('太阳与月亮','settings-section-title'),False,False,4)
        self.detail_grid([('日出',sky.get('sunrise','—')),('日落',sky.get('sunset','—'))])
        minutes=sky.get('daylight')
        summary=(tr('昼长 %s 小时 %s 分钟') % divmod(minutes,60)) if type(minutes) is int else tr('暂无日照时长数据')
        if sky.get('date'):summary+=' · '+sky['date']
        self.pack_start(label(summary,'dim-label'),False,False,0)
        moon=Gtk.Expander(label=tr('月相与月升月落'))
        moon_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8,margin_top=8)
        phases={'New Moon':'新月','Waxing Crescent':'蛾眉月','First Quarter':'上弦月','Waxing Gibbous':'盈凸月','Full Moon':'满月','Waning Gibbous':'亏凸月','Last Quarter':'下弦月','Waning Crescent':'残月'}
        phase=tr(phases.get(sky.get('phase'),sky.get('phase',''))) or tr('暂无数据')
        moon_box.pack_start(label(phase+' · '+tr('照明比例')+' '+sky.get('illumination','—')+'%','weather-summary'),False,False,0)
        moon_box.pack_start(label(tr('月升')+' '+sky.get('moonrise','—')+'    '+tr('月落')+' '+sky.get('moonset','—'),'dim-label'),False,False,0)
        moon.add(moon_box);self.pack_start(moon,False,False,0)
        self.show_all();self.reflow_hours(self,self.get_allocation())

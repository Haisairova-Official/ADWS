"""Explicit location lookup: system first, IP only after a UI consent action."""
import json
import math
import threading
import time
import urllib.request
import urllib.parse
from gi.repository import Gio,GLib,Gtk
from adws_i18n import tr, chinese
from adws_system_settings import label


from adws_location_registration import register_location_app


def coordinates(latitude,longitude):
    if isinstance(latitude,bool) or isinstance(longitude,bool):raise ValueError('Invalid coordinates')
    lat,lon=float(latitude),float(longitude)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
        raise ValueError('Invalid coordinates')
    return round(lat,4),round(lon,4)


def json_request(url,limit=512*1024):
    request=urllib.request.Request(url,headers={'User-Agent':'ADWS-sidebar/1'})
    with urllib.request.urlopen(request,timeout=8) as response:raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('Response too large')
    return json.loads(raw)


def city_location(city):
    city=str(city).strip()
    if not city or len(city)>120:raise ValueError(tr('请输入城市名称。'))
    # Explicit coordinates are also valid manual locations, without device lookup.
    parts=city.split(',')
    if len(parts)==2:
        try:
            lat,lon=coordinates(*parts)
            return {'latitude':lat,'longitude':lon,'name':city,'source':'city'}
        except (TypeError,ValueError):pass
    query=urllib.parse.urlencode({'name':city,'count':1,'language':'zh' if chinese() else 'en','format':'json'})
    data=json_request('https://geocoding-api.open-meteo.com/v1/search?'+query,65536)
    results=data.get('results')
    if not results and len(city)<=20 and all('\u4e00'<=char<='\u9fff' for char in city) and not city.endswith(('市','县','区')):
        query=urllib.parse.urlencode({'name':city+'市','count':1,'language':'zh','format':'json'})
        results=json_request('https://geocoding-api.open-meteo.com/v1/search?'+query,65536).get('results')
    if not isinstance(results,list) or not results:raise ValueError(tr('没有找到该城市，请补充省份或国家。'))
    item=results[0];lat,lon=coordinates(item.get('latitude'),item.get('longitude'))
    name=' · '.join(dict.fromkeys(str(item[key])[:100] for key in ('name','admin1','country') if item.get(key)))
    return {'latitude':lat,'longitude':lon,'name':name or city,'source':'city'}


def ip_location(*,consent=False):
    if consent is not True:raise PermissionError('IP location requires consent')
    data=json_request('https://ipapi.co/json/',65536)
    if data.get('error'):raise ValueError('IP location unavailable')
    lat,lon=coordinates(data.get('latitude'),data.get('longitude'))
    return {'latitude':lat,'longitude':lon,'name':str(data.get('city') or tr('大致位置'))[:120],'source':'ip'}


def system_location(cancel):
    bus=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
    destination='org.freedesktop.GeoClue2';manager='/org/freedesktop/GeoClue2/Manager';client=None
    def call(path,interface,method,args=None):
        return bus.call_sync(destination,path,interface,method,args,None,Gio.DBusCallFlags.NONE,2000,None).unpack()
    try:
        client=call(manager,destination+'.Manager','CreateClient')[0]
        for name,value in [('DesktopId',GLib.Variant('s',register_location_app())),('RequestedAccuracyLevel',GLib.Variant('u',4))]:
            call(client,'org.freedesktop.DBus.Properties','Set',GLib.Variant('(ssv)',(destination+'.Client',name,value)))
        call(client,destination+'.Client','Start')
        deadline=time.monotonic()+6
        while time.monotonic()<deadline and not cancel.is_set():
            location=call(client,'org.freedesktop.DBus.Properties','Get',GLib.Variant('(ss)',(destination+'.Client','Location')))[0]
            if isinstance(location,str) and location!='/':
                data=call(location,'org.freedesktop.DBus.Properties','GetAll',GLib.Variant('(s)',(destination+'.Location',)))[0]
                lat,lon=coordinates(data.get('Latitude'),data.get('Longitude'))
                return {'latitude':lat,'longitude':lon,'name':str(data.get('Description') or tr('当前位置'))[:120],'source':'system'}
            cancel.wait(.25)
        raise TimeoutError('Location unavailable')
    finally:
        if client:
            try:call(client,destination+'.Client','Stop')
            except GLib.Error:pass
            try:call(manager,destination+'.Manager','DeleteClient',GLib.Variant('(o)',(client,)))
            except GLib.Error:pass


class LocationChooser(Gtk.Box):
    def __init__(self,host,changed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        self.host=host;self.changed=changed;self.generation=0;self.cancel=threading.Event();self.closed=False
        row=Gtk.Box(spacing=8);self.button=Gtk.Button(label=tr('使用当前位置'))
        self.button.connect('clicked',lambda *_:self.start());row.pack_start(self.button,False,False,0)
        clear=Gtk.Button(label=tr('清除位置'));clear.connect('clicked',self.clear);row.pack_start(clear,False,False,0)
        self.pack_start(row,False,False,0)
        self.status=label('未获取位置；自动潮汐暂不可用。','dim-label');self.status.set_max_width_chars(42);self.pack_start(self.status,False,False,0)
        self.prompt=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        caption=label('系统定位不可用。是否允许通过 ipapi.co 查询 IP 对应的大致位置？位置仅用于天气和潮汐查询。')
        caption.set_max_width_chars(42);self.prompt.pack_start(caption,False,False,0)
        actions=Gtk.Box(spacing=8)
        allow=Gtk.Button(label=tr('允许此次 IP 查询'));allow.connect('clicked',lambda *_:self.start(use_ip=True))
        deny=Gtk.Button(label=tr('不允许'));deny.connect('clicked',self.clear)
        actions.pack_start(allow,False,False,0);actions.pack_start(deny,False,False,0);self.prompt.pack_start(actions,False,False,0)
        self.prompt.set_no_show_all(True);self.pack_start(self.prompt,False,False,0)
        self.connect('destroy',self.dispose)

    def dispose(self,*_):self.closed=True;self.generation+=1;self.cancel.set()

    def use_city(self):
        self.generation+=1;self.cancel.set();self.prompt.hide();self.button.set_sensitive(True)
        self.status.set_text(tr("使用指定城市，无需定位。"))

    def clear(self,*_):
        self.generation+=1;self.cancel.set();self.prompt.hide();self.button.set_sensitive(True)
        self.status.set_text(tr('未获取位置；自动潮汐暂不可用。'));self.changed(None)

    def start(self,use_ip=False):
        self.generation+=1;token=self.generation;self.cancel.set();self.cancel=threading.Event();cancel=self.cancel
        self.prompt.hide();self.button.set_sensitive(False);self.status.set_text(tr('正在获取位置…'))
        # Discard any prior location so failure cannot silently reuse an old coast.
        self.changed(None)
        def worker():
            try:result=ip_location(consent=True) if use_ip else system_location(cancel)
            except Exception:result=None
            def done():
                if self.closed or self.host.closed or token!=self.generation:return False
                self.button.set_sensitive(True)
                if result:
                    self.status.set_text(result['name']+' · '+tr('IP 大致位置' if use_ip else '系统位置'))
                    self.changed(result)
                elif not use_ip:
                    self.status.set_text(tr('系统定位不可用'))
                    self.prompt.set_no_show_all(False);self.prompt.show_all();self.prompt.set_no_show_all(True)
                else:self.status.set_text(tr('定位失败，相关信息暂不可用。'))
                return False
            if not self.closed:GLib.idle_add(done)
        threading.Thread(target=worker,name='adws-location',daemon=True).start()

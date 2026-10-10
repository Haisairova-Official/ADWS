"""Bounded, in-memory static clipboard thumbnails. No files or image networking."""
import gi
gi.require_version('GdkPixbuf','2.0')
from gi.repository import GdkPixbuf, GLib


def dimensions(data, kind):
    if kind=='png':
        if len(data)<24 or data[12:16]!=b'IHDR':return 0,0
        return int.from_bytes(data[16:20],'big'),int.from_bytes(data[20:24],'big')
    index=2
    while index+4<=len(data):
        if data[index]!=255:return 0,0
        while index<len(data) and data[index]==255:index+=1
        if index>=len(data):break
        marker=data[index];index+=1
        if marker in (0xd9,0xda):break
        if marker==1 or 0xd0<=marker<=0xd8:continue
        size=int.from_bytes(data[index:index+2],'big')
        if size<2 or index+size>len(data):break
        if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf) and size>=8:
            return int.from_bytes(data[index+5:index+7],'big'),int.from_bytes(data[index+3:index+5],'big')
        index+=size
    return 0,0


def thumbnail(data):
    # Only static raster decoders: avoid SVG external resources and animated files.
    kind='png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'jpeg' if data.startswith(b'\xff\xd8\xff') else None
    if kind is None or len(data)>8*1024*1024:return None
    width,height=dimensions(data,kind)
    if width<1 or height<1 or width*height>16_000_000:return None
    loader=GdkPixbuf.PixbufLoader.new_with_type(kind);oversized=False
    def sized(_,width,height):
        nonlocal oversized
        oversized=width<1 or height<1 or width*height>16_000_000
        ratio=min(1,320/max(1,width),160/max(1,height))
        loader.set_size(1 if oversized else max(1,round(width*ratio)),1 if oversized else max(1,round(height*ratio)))
    loader.connect('size-prepared',sized)
    try:
        loader.write(data);loader.close()
        return None if oversized else loader.get_pixbuf()
    except GLib.Error:
        try:loader.close()
        except GLib.Error:pass
        return None

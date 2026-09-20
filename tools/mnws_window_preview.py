#!/usr/bin/env python3
"""Private thumbnail stream: Niri/Mutter ScreenCast -> PipeWire -> stdout.
No screenshot actions, clipboard access, disk images, or shell commands.
One process belongs to one visible popup; SIGTERM closes all capture sessions.
"""
import base64
import json
import signal
import sys
import threading
import warnings
import time


def main(ids):
    import ctypes,os
    parent=os.getppid()
    # Close captures if the owning taskbar crashes or is force-stopped.
    ctypes.CDLL(None).prctl(1,signal.SIGTERM)
    if os.getppid()!=parent:return 1
    import gi
    warnings.filterwarnings('ignore',category=DeprecationWarning)
    gi.require_version('Gst', '1.0')
    gi.require_version('GstApp', '1.0')
    from gi.repository import Gio, GLib, Gst
    Gst.init(None)
    if any(Gst.ElementFactory.find(name) is None for name in ('pipewiresrc','videorate','videoconvert','videoscale','pngenc','appsink')):
        raise RuntimeError('Missing GStreamer preview components')
    bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    service='org.gnome.Mutter.ScreenCast'
    loop=GLib.MainLoop()
    pipelines=[];subscriptions=[];session=None
    write_lock=threading.Lock()
    last_frame={};frames=set()
    def call(path,interface,method,args=None):
        return bus.call_sync(service,path,interface,method,args,None,0,2000,None)
    def quit_loop(*_):
        loop.quit();return False
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,quit_loop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGINT,quit_loop)
    def sample(sink,window_id):
        now=time.monotonic()
        buffer=sink.emit('pull-sample').get_buffer()
        if now-last_frame.get(window_id,0)<.45:return Gst.FlowReturn.OK
        last_frame[window_id]=now
        ok,mapped=buffer.map(Gst.MapFlags.READ)
        if not ok:return Gst.FlowReturn.ERROR
        try:
            line=json.dumps({'id':window_id,'png':base64.b64encode(mapped.data).decode('ascii')},separators=(',',':'))+'\n'
            with write_lock:
                sys.stdout.write(line);sys.stdout.flush()
            frames.add(window_id)
        except (BrokenPipeError,OSError):
            GLib.idle_add(quit_loop)
            return Gst.FlowReturn.EOS
        finally:buffer.unmap(mapped)
        return Gst.FlowReturn.OK
    def stream_added(_bus,_sender,_path,_iface,_signal,parameters,window_id):
        node=parameters.unpack()[0]
        pipeline=Gst.parse_launch(f'pipewiresrc path={int(node)} do-timestamp=true ! queue max-size-buffers=1 leaky=downstream ! videorate drop-only=true max-rate=2 ! video/x-raw,framerate=2/1 ! videoconvert ! videoscale add-borders=true ! video/x-raw,width=240,height=150,pixel-aspect-ratio=1/1 ! pngenc compression-level=1 ! appsink name=frames emit-signals=true sync=false max-buffers=1 drop=true')
        pipeline.get_by_name('frames').connect('new-sample',sample,window_id)
        pipeline.get_bus().add_signal_watch()
        pipeline.get_bus().connect('message::error',lambda *_:GLib.idle_add(quit_loop))
        pipelines.append(pipeline)
        pipeline.set_state(Gst.State.PLAYING)
    try:
        session=call('/org/gnome/Mutter/ScreenCast',service,'CreateSession',GLib.Variant('(a{sv})',({},))).unpack()[0]
        for window_id in ids:
            stream=call(session,service+'.Session','RecordWindow',GLib.Variant('(a{sv})',({'window-id':GLib.Variant('t',window_id),'cursor-mode':GLib.Variant('u',0)},))).unpack()[0]
            subscriptions.append(bus.signal_subscribe(service,service+'.Stream','PipeWireStreamAdded',stream,None,0,stream_added,window_id))
        call(session,service+'.Session','Start')
        GLib.timeout_add_seconds(6,lambda:quit_loop() if not frames else False)
        loop.run()
    finally:
        for pipeline in pipelines:pipeline.set_state(Gst.State.NULL)
        for subscription in subscriptions:bus.signal_unsubscribe(subscription)
        if session:
            try:call(session,service+'.Session','Stop')
            except GLib.Error:pass
    return 0 if frames else 1

if __name__=='__main__':
    try:raise SystemExit(main([int(value) for value in sys.argv[1:]]))
    except Exception as error:
        print('MNWS window preview: '+str(error),file=sys.stderr)
        raise SystemExit(1)

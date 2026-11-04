"""Small desktop lyrics media footer; one bounded audio sampler per desktop host."""
import atexit
import math
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import threading
import time

BARS=32


def parse_frame(raw):
    try:values=[int(x) for x in raw.strip().split(b';') if x]
    except ValueError:return None
    return tuple(max(0,min(1000,x))/1000 for x in values) if len(values)==BARS else None


def progress_values(position,duration):
    try:
        position=float(position);duration=float(duration)
        if not math.isfinite(position) or not math.isfinite(duration) or duration<=0:return None
        return max(0,min(position,duration)),duration
    except (TypeError,ValueError):return None


class SpectrumSource:
    def __init__(self):
        self.condition=threading.Condition();self.users=set();self.thread=None;self.closed=False
        self.values=(0.,)*BARS;self.updated=0.;self.status='idle';self.process=None

    def acquire(self,owner):
        with self.condition:
            if self.closed:return
            self.users.add(owner)
            if self.thread is None:
                self.thread=threading.Thread(target=self.run,daemon=True,name='desktop-spectrum');self.thread.start()
            self.condition.notify_all()

    def release(self,owner):
        with self.condition:self.users.discard(owner);self.condition.notify_all()

    def active(self):
        with self.condition:return bool(self.users) and not self.closed

    def snapshot(self):
        with self.condition:
            return (self.values if time.monotonic()-self.updated<.6 else (0.,)*BARS),self.status

    def close(self):
        with self.condition:self.closed=True;self.users.clear();self.condition.notify_all()
        if self.thread:self.thread.join(timeout=3)

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or self.users)
                if self.closed:return
            child=None;failed=False
            try:
                if not shutil.which('cava'):raise FileNotFoundError('cava')
                # Explicit output monitor: never fall back to a capture/microphone device.
                sink=subprocess.check_output(['pactl','get-default-sink'],timeout=2,text=True,stderr=subprocess.DEVNULL).strip()
                if not sink or any(c in sink for c in '\r\n[]'):raise ValueError('Invalid output sink')
                config=f'''[general]
bars = {BARS}
framerate = 30
sleep_timer = 3
[input]
method = pulse
source = {sink}.monitor
[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 1000
bar_delimiter = 59
frame_delimiter = 10
'''
                with tempfile.TemporaryDirectory(prefix='adws-lyrics-spectrum-') as directory:
                    path=Path(directory)/'config';path.write_text(config)
                    child=subprocess.Popen(['cava','-p',str(path)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                    self.process=child
                    with self.condition:self.status='ready'
                    with selectors.DefaultSelector() as selector:
                        selector.register(child.stdout,selectors.EVENT_READ);buffer=b'';check_sink=time.monotonic()+5;changed_sink=False
                        while self.active() and child.poll() is None:
                            if time.monotonic()>=check_sink:
                                current=subprocess.check_output(['pactl','get-default-sink'],timeout=2,text=True,stderr=subprocess.DEVNULL).strip()
                                check_sink=time.monotonic()+5
                                if current!=sink:changed_sink=True;break
                            if not selector.select(.2):continue
                            chunk=os.read(child.stdout.fileno(),4096)
                            if not chunk:break
                            buffer+=chunk
                            while b'\n' in buffer:
                                line,buffer=buffer.split(b'\n',1);values=parse_frame(line)
                                if values is not None:
                                    with self.condition:self.values=values;self.updated=time.monotonic()
                            if len(buffer)>8192:raise ValueError('Oversized spectrum frame')
                    if self.active() and not changed_sink:raise RuntimeError('Audio source stopped')
            except Exception as error:
                failed=True
                with self.condition:self.status='missing' if isinstance(error,FileNotFoundError) and error.args==('cava',) else 'unavailable'
            finally:
                if child:
                    if child.poll() is None:
                        child.terminate()
                        try:child.wait(timeout=1)
                        except subprocess.TimeoutExpired:child.kill();child.wait()
                    child.stdout.close()
                self.process=None
                with self.condition:self.values=(0.,)*BARS
            with self.condition:
                if failed and self.users and not self.closed:self.condition.wait(timeout=15)


SOURCE=SpectrumSource()
atexit.register(SOURCE.close)

# Import GTK only for the presentation layer; parsing/lifecycle can be tested headlessly.
def media_widget(settings, seek_callback=None):
    from gi.repository import Gtk,GLib
    from adws_i18n import tr

    class Media(Gtk.Box):
        def __init__(self):
            super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=3)
            self.get_style_context().add_class('desktop-media');self.set_margin_top(4)
            self.playing=False;self.timer=0;self.values=[0.]*BARS;self.last=0.;self.alive=True
            self.spectrum=Gtk.DrawingArea();self.spectrum.set_size_request(-1,24)
            self.spectrum.get_style_context().add_class('desktop-spectrum')
            self.spectrum.set_no_show_all(True);self.spectrum.set_visible(settings.get('show_spectrum',True))
            self.spectrum.connect('draw',self.draw);self.pack_start(self.spectrum,False,False,0)
            self.row=Gtk.Box(spacing=7)
            self.elapsed=Gtk.Label(label='--:--');self.total=Gtk.Label(label='--:--')
            self.progress=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,1,.001);self.progress.set_draw_value(False);self.progress.set_hexpand(True);self.progress.set_valign(Gtk.Align.CENTER)
            self.progress.get_style_context().add_class('desktop-progress')
            self.identity=None;self.position=None;self.drag_identity=None;self.dragging=False;self.pointer_down=False
            self.syncing=False;self.seek_timer=0;self.pending=None;self.seekable=False
            self.progress.connect('button-press-event',self.press)
            self.progress.connect_after('button-release-event',self.release)
            self.progress.connect('value-changed',self.changed)
            self.row.pack_start(self.elapsed,False,False,0);self.row.pack_start(self.progress,True,True,0);self.row.pack_start(self.total,False,False,0)
            self.pack_start(self.row,False,False,0)
            self.row.show_all();self.row.set_no_show_all(True);self.row.set_visible(settings.get('show_progress',True))
            self.connect('map',lambda *_:self.reconcile());self.connect('unmap',lambda *_:(self.suspend(),self.cancel_seek()))
            self.connect('destroy',lambda *_:self.close())

        @staticmethod
        def clock(seconds):
            minutes,seconds=divmod(int(seconds),60);return f'{minutes}:{seconds:02d}'

        def update(self,payload):
            values=progress_values(payload.get('position'),payload.get('duration'))
            identity=(payload.get('player'),payload.get('track_id'),values[1] if values else None,payload.get('track_token'))
            if identity!=self.identity:
                self.cancel_seek();self.identity=identity
            self.position=values
            self.seekable=bool(values and payload.get('can_seek') and identity[0] and identity[1] and identity[3] and seek_callback)
            self.progress.set_sensitive(self.seekable)
            if self.pending and (time.monotonic()>self.pending[1] or (values and abs(values[0]-self.pending[0])<2)):
                self.pending=None
            if not self.dragging and not self.seek_timer and not self.pending:self.restore_position()
            self.total.set_text(self.clock(values[1]) if values else '--:--')
            self.progress.set_tooltip_text(tr('拖动调整播放进度') if self.seekable else tr('播放器不支持跳转播放进度'))
            self.playing=bool(payload.get('playing'));self.reconcile()

        def restore_position(self):
            self.syncing=True
            self.progress.set_value(self.position[0]/self.position[1] if self.position else 0)
            self.syncing=False
            self.elapsed.set_text(self.clock(self.position[0]) if self.position else '--:--')

        def press(self,widget,event):
            if event.button==1 and self.seekable:
                self.cancel_seek();self.pointer_down=True;self.dragging=True;self.drag_identity=self.identity
            return False

        def release(self,widget,event):
            if event.button==1:
                self.pointer_down=False
                if self.dragging:self.dragging=False;self.commit_seek()
                else:self.restore_position()
            return False

        def changed(self,*_):
            if self.syncing or not self.seekable or (self.pointer_down and not self.dragging):return
            self.elapsed.set_text(self.clock(self.progress.get_value()*self.identity[2]))
            if not self.dragging:
                self.drag_identity=self.identity
                if self.seek_timer:GLib.source_remove(self.seek_timer)
                self.seek_timer=GLib.timeout_add(160,self.commit_seek)

        def commit_seek(self):
            self.seek_timer=0
            if self.alive and self.seekable and self.drag_identity==self.identity:
                position=self.progress.get_value()*self.identity[2]
                if seek_callback(position,self.identity[0],self.identity[1],self.identity[3]):
                    self.pending=(position,time.monotonic()+4)
                    return False
            self.restore_position();return False

        def cancel_seek(self):
            if self.seek_timer:GLib.source_remove(self.seek_timer);self.seek_timer=0
            self.dragging=False;self.drag_identity=None;self.pending=None

        def seek_finished(self,success):
            if not success:self.pending=None;self.restore_position()

        def reconcile(self):
            active=self.alive and self.get_mapped() and self.playing and self.spectrum.get_visible()
            if active and not self.timer:
                SOURCE.acquire(self);self.last=time.monotonic();self.timer=GLib.timeout_add(33,self.animate)
            elif not active:self.suspend()

        def suspend(self):
            SOURCE.release(self)
            if self.timer:GLib.source_remove(self.timer);self.timer=0
            self.values=[0.]*BARS;self.spectrum.queue_draw()

        def close(self):
            if not self.alive:return
            self.alive=False;self.cancel_seek();self.suspend()

        def animate(self):
            target,status=SOURCE.snapshot();now=time.monotonic();dt=min(.2,max(0,now-self.last));self.last=now
            changed=False
            for i,v in enumerate(target):
                factor=1-math.exp(-dt*(24 if v>self.values[i] else 9))
                updated=self.values[i]+(v-self.values[i])*factor
                if abs(updated-self.values[i])>.001:changed=True
                self.values[i]=updated
            tooltip={'missing':'安装 CAVA 后可显示频谱','unavailable':'音频输出不可用，频谱暂不可用'}.get(status,'系统播放音频频谱')
            if getattr(self,'last_status',None)!=status:self.last_status=status;self.spectrum.set_tooltip_text(tr(tooltip))
            if changed:self.spectrum.queue_draw()
            return True

        def draw(self,widget,cr):
            color=widget.get_style_context().get_color(Gtk.StateFlags.NORMAL)
            width,height=widget.get_allocated_width(),widget.get_allocated_height();step=width/BARS
            cr.rectangle(0,0,width,height);cr.clip()
            gradient=__import__('cairo').LinearGradient(0,0,0,height)
            gradient.add_color_stop_rgba(0,color.red,color.green,color.blue,.85)
            gradient.add_color_stop_rgba(1,color.red,color.green,color.blue,.25);cr.set_source(gradient)
            for i,value in enumerate(self.values):
                h=max(1,value*(height-1));cr.rectangle(i*step+1,height-h,max(1,step-2),h)
            cr.fill();return False

    return Media()

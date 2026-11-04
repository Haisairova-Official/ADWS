"""Bounded desktop consumer of the existing plugin runner/watchdog protocol."""
import json
import os
from pathlib import Path
import signal
import socket
import tempfile
import shutil
import subprocess
import sys
import threading
import time
from adws_i18n import tr


class PluginStream:
    def __init__(self, definition, row):
        self.stop_event=threading.Event();self.lock=threading.Lock();self.latest=None;self.process=None
        self.definition,self.row=definition,row
        self.event_dir=None;self.event_path=None;self.last_event=0.
        if definition['manifest'].get('renderer')=='desktop.widgets-v1':
            self.event_dir=tempfile.mkdtemp(prefix='adws-widget-')
            self.event_path=str(Path(self.event_dir)/'events.sock')
        self.thread=threading.Thread(target=self.run,daemon=True,name='desktop-plugin')
        self.thread.start()

    def put(self,value):
        with self.lock: self.latest=value

    def take(self):
        with self.lock:
            value,self.latest=self.latest,None
        return value

    def run(self):
        runner=Path(__file__).with_name('adws_plugin_runner.py')
        command=[sys.executable,str(runner),str(self.definition['file']),'--settings-json',json.dumps(self.row['settings'],ensure_ascii=False)]
        component=self.definition['manifest'].get('componentId')
        if component: command+=['--component',component]
        try:
            with self.lock:
                if self.stop_event.is_set(): return
                self.process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    env={**os.environ,'ADWS_PLUGIN_INSTANCE':self.row['instance'],'ADWS_COMPONENT_HOST':'desktop','ADWS_PLUGIN_HOST_PID':str(os.getpid()),**({'ADWS_DESKTOP_EVENT_SOCKET':self.event_path} if self.event_path else {})},start_new_session=True)
                process=self.process
            while not self.stop_event.is_set():
                line=process.stdout.readline(1024*1024+1)
                if not line: break
                if len(line)>1024*1024: raise ValueError('Plugin output exceeded limit')
                value=json.loads(line)
                if not isinstance(value,dict): raise ValueError('Invalid plugin payload')
                self.put(value)
            code=process.wait()
            if not self.stop_event.is_set() and code:
                self.put({'class':'error','primary':tr('桌面组件运行失败'),'secondary':tr('请打开组件菜单重试，或查看插件故障记录。')})
        except (OSError,ValueError) as error:
            if not self.stop_event.is_set(): self.put({'class':'error','primary':tr('桌面组件不可用'),'secondary':str(error)[:512]})
        finally:
            process=self.process
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                        process.wait()
                if process.stdout:process.stdout.close()
            if self.event_dir:shutil.rmtree(self.event_dir,ignore_errors=True)

    def event(self,action,value=None):
        if not self.event_path or self.stop_event.is_set():return False
        payload=json.dumps({'action':action,'value':value},ensure_ascii=False).encode()
        if len(payload)>128*1024:return False
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as channel:
                channel.setblocking(False);channel.sendto(payload,self.event_path);self.last_event=time.monotonic()
            return True
        except OSError:return False

    def close(self):
        self.stop_event.set()
        with self.lock:
            process=self.process
        if process is not None and process.poll() is None:
            def terminate():
                # Allow the final debounced note edit to be persisted before termination.
                if self.event_path and time.monotonic()-self.last_event<.5:time.sleep(.4)
                try:
                    process.send_signal(signal.SIGCONT);process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait()
                except ProcessLookupError:pass
            threading.Thread(target=terminate,daemon=True,name='desktop-plugin-stop').start()


class SharedStream:
    """One plugin process per desktop instance, with independent display cursors.

    All lease methods run on GTK's main thread; the underlying stream owns its
    worker lock. Mirroring a widget must not create competing state writers.
    """
    def __init__(self,source,on_close):
        self.source,self.on_close=source,on_close
        self.latest=None;self.serial=0;self.users=0

    def subscribe(self):
        self.users+=1
        return StreamLease(self)


class StreamLease:
    def __init__(self,shared):
        self.shared=shared;self.seen=0;self.closed=False

    @property
    def thread(self):return self.shared.source.thread

    @property
    def process(self):return self.shared.source.process

    @property
    def event_dir(self):return self.shared.source.event_dir

    def take(self):
        if self.closed:return None
        shared=self.shared;value=shared.source.take()
        if value is not None:shared.latest=value;shared.serial+=1
        if self.seen==shared.serial:return None
        self.seen=shared.serial
        import copy
        return copy.deepcopy(shared.latest)

    def event(self,action,value=None):
        return not self.closed and self.shared.source.event(action,value)

    def close(self):
        if self.closed:return
        self.closed=True;shared=self.shared;shared.users-=1
        if shared.users==0:shared.source.close();shared.on_close()

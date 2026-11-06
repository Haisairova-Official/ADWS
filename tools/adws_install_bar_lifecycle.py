"""Preserve only reviewed running top bars across an installer transaction.

The caller stops bars before taking a configuration snapshot. On failure it
must call stop_new(), restore files, then restore_old(); close() only releases
process handles and does not terminate successfully installed bars. Process
environments never enter serialized plans, logs or reports.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import select
import signal
import subprocess


@contextmanager
def _defer_launch_cancellation():
    """Record a spawned child before cancellation, without inherited masks."""
    pending=[]
    def defer(signum,frame):pending.append((signum,frame))
    previous={sig:signal.signal(sig,defer) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:yield
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
        for sig,frame in pending:
            handler=previous[sig]
            if handler==signal.SIG_IGN:continue
            if callable(handler):handler(sig,frame)
            else:raise KeyboardInterrupt('Top bar restart cancelled')


def _environment(values):
    return {key:value for key,value in values.items()
            if not key.startswith('ADWS_INSTALL_')
            and key not in ('ADWS_NIRI_METHOD','ADWS_BUILD_MIRROR')}


def _identity(pid):
    proc=Path('/proc')/str(pid)
    if proc.stat().st_uid!=os.getuid():raise ValueError('Top bar belongs to another user')
    return (proc/'stat').read_text().rsplit(')',1)[1].split()[19]


def _exited(fd,timeout=0):
    return bool(select.select([fd],[],[],timeout)[0])


class TopbarLifecycle:
    """In-memory rollback state for explicitly reviewed Waybar profiles."""
    def __init__(self, profiles, log_dir, *, processes=None, popen=None, stop_timeout=3.0, startup_grace=.65):
        from adws_waybar import processes as running, is_adws
        self.processes=processes or running
        self.popen=popen or subprocess.Popen
        self.log_dir=Path(log_dir)
        self.stop_timeout=stop_timeout
        self.startup_grace=startup_grace
        self.profiles={}
        for profile in profiles:
            config=Path(profile['config']).expanduser().resolve()
            style=Path(profile['style']).expanduser().resolve()
            if is_adws(config) or is_adws(style):raise ValueError('Bottom taskbar is not a top bar migration profile')
            if config in self.profiles and self.profiles[config]!=style:
                raise ValueError('Top bar profile has conflicting styles')
            self.profiles[config]=style
        self.rows=[]
        self.children=[]
        self.captured=False
        self.closed=False

    def _matches(self, config, style):
        matches=[row for row in self.processes() if Path(row['config']).resolve()==config]
        if len(matches)>1:raise RuntimeError('Multiple Waybar processes use the reviewed top bar profile: '+str(config))
        if matches and Path(matches[0]['style']).resolve()!=style:
            raise RuntimeError('Running top bar uses a different stylesheet: '+str(config))
        return matches

    def capture(self):
        if self.captured or self.closed:raise RuntimeError('Top bar lifecycle cannot be captured twice')
        if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
            if self.profiles:raise RuntimeError('Safe top bar process handles are unavailable')
        try:
            for config,style in self.profiles.items():
                matches=self._matches(config,style)
                if not matches:continue
                current=matches[0];pid=current['pid'];start=current['start']
                fd=None
                try:
                    if _identity(pid)!=start:raise RuntimeError('Top bar changed while capturing its session')
                    fd=os.pidfd_open(pid)
                    proc=Path('/proc')/str(pid)
                    env=dict(os.fsdecode(item).split('=',1) for item in (proc/'environ').read_bytes().split(b'\0') if b'=' in item)
                    argv=[os.fsdecode(value) for value in (proc/'cmdline').read_bytes().split(b'\0') if value]
                    cwd=(proc/'cwd').resolve(strict=True)
                    if _identity(pid)!=start or _exited(fd) or argv!=current['argv'] or cwd!=Path(current['cwd']):
                        raise RuntimeError('Top bar changed while capturing its session')
                    self.rows.append({'pid':pid,'start':start,'fd':fd,'config':config,'style':style,
                                      'argv':argv,'cwd':cwd,'env':_environment(env),
                                      'stop_requested':False,'stopped':False,'restored':False})
                    fd=None
                finally:
                    if fd is not None:os.close(fd)
            self.captured=True
            return [{'pid':row['pid'],'config':str(row['config']),'style':str(row['style'])} for row in self.rows]
        except BaseException:
            self.close()
            raise

    def _ready(self):
        if not self.captured or self.closed:raise RuntimeError('Top bar lifecycle is not captured')

    def stop(self):
        self._ready()
        for row in self.rows:
            if row['stopped']:continue
            # Mark the intention before signaling: interrupted waits can be
            # completed by restore_old(), which never duplicates a live bar.
            row['stop_requested']=True
            if not _exited(row['fd']):
                try:signal.pidfd_send_signal(row['fd'],signal.SIGTERM)
                except ProcessLookupError:pass
            if not _exited(row['fd'],self.stop_timeout):
                raise RuntimeError('Top bar did not exit normally; no forced termination: '+str(row['config']))
            row['stopped']=True
            if self._matches(row['config'],row['style']):
                raise RuntimeError('Top bar was automatically restarted; review its service ownership')

    def _spawn(self,row,phase):
        if self._matches(row['config'],row['style']):
            raise RuntimeError('Top bar appeared during installation; refusing to start a duplicate')
        self.log_dir.mkdir(parents=True,exist_ok=True)
        log=self.log_dir/(str(self.rows.index(row))+'-'+phase+'.log')
        child_record={'child':None,'fd':None,'phase':phase,'row':row}
        with log.open('ab') as output:
            # Delaying Python signal handlers across Popen+assignment prevents
            # an orphan in the narrow child-created/handle-not-recorded gap.
            with _defer_launch_cancellation():
                child=self.popen(row['argv'],cwd=row['cwd'],env=row['env'],stdin=subprocess.DEVNULL,
                                 stdout=output,stderr=output,start_new_session=True)
                child_record['child']=child
                self.children.append(child_record)
                try:child_record['fd']=os.pidfd_open(child.pid)
                except ProcessLookupError:pass
        try:child.wait(timeout=self.startup_grace)
        except subprocess.TimeoutExpired:
            if phase=='restore':row['restored']=True
            return {'pid':child.pid,'config':str(row['config']),'style':str(row['style']),'log':str(log)}
        raise RuntimeError('Top bar exited while restarting; see '+str(log))

    def start_new(self):
        self._ready()
        if any(not row['stopped'] for row in self.rows):
            raise RuntimeError('Top bar stop has not completed')
        if any(child['phase']=='new' for child in self.children):raise RuntimeError('New top bars were already started')
        return [self._spawn(row,'new') for row in self.rows if row['stopped']]

    def stop_new(self):
        """Must succeed before the caller restores the configuration snapshot."""
        self._ready()
        errors=[]
        for record in self.children:
            if record['phase']!='new':continue
            child=record['child'];fd=record['fd']
            try:
                if fd is not None:
                    if not _exited(fd):
                        try:signal.pidfd_send_signal(fd,signal.SIGTERM)
                        except ProcessLookupError:pass
                    if not _exited(fd,self.stop_timeout):raise RuntimeError('New top bar did not exit normally')
                    child.wait(timeout=0)
                elif child.poll() is None:
                    # Only our unreaped child can enter this fallback (e.g.
                    # pidfd allocation failed immediately after Popen).
                    child.terminate();child.wait(timeout=self.stop_timeout)
            except (OSError,subprocess.TimeoutExpired,RuntimeError) as error:
                errors.append(str(record['row']['config'])+': '+str(error))
        if errors:raise RuntimeError('; '.join(errors))

    def restore_old(self):
        """Call only after files were restored, including when stop was cancelled."""
        if not self.captured or self.closed:return []
        self._ready()
        restored=[];errors=[];cancelled=None
        for row in self.rows:
            if not row['stop_requested'] or row['restored']:continue
            try:
                if not _exited(row['fd'],self.stop_timeout):
                    # The original process never stopped; keep it instead of
                    # duplicating it or escalating to a kill.
                    continue
                row['stopped']=True
                restored.append(self._spawn(row,'restore'))
            except Exception as error:
                errors.append(str(row['config'])+': '+str(error))
            except BaseException as error:
                # Finish independent restorations before re-raising a repeated
                # cancellation; it is never converted into a success result.
                cancelled=error
        if errors:raise RuntimeError('Top bar recovery incomplete: '+'; '.join(errors)) from cancelled
        if cancelled is not None:raise cancelled
        return restored

    def close(self):
        """Release descriptors and environment copies; do not stop healthy bars."""
        if self.closed:return
        for item in [*self.rows,*self.children]:
            fd=item.get('fd')
            if fd is not None:
                os.close(fd);item['fd']=None
        for row in self.rows:row['env'].clear()
        self.closed=True

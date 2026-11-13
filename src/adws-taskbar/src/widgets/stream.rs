//! One worker per mounted stream. Only the latest unpublished value is retained.
use gtk::glib;
use std::{
    cell::RefCell,
    io::{self, Read},
    os::fd::{AsRawFd, RawFd},
    os::unix::net::UnixStream,
    rc::Rc,
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

pub(super) struct Worker {
    stop: Option<UnixStream>,
    source: Option<glib::SourceId>,
    timer: Rc<RefCell<Option<glib::SourceId>>>,
    thread: Option<thread::JoinHandle<()>>,
}
struct Latest<T> {
    pending: Mutex<Mailbox<T>>,
    notify: glib::SyncSender<()>,
}
struct Mailbox<T> {
    value: Option<T>,
    scheduled: bool,
}
pub(super) struct Updates<T>(Arc<Latest<T>>);
impl<T> Updates<T> {
    pub fn publish(&self, value: T) {
        let mut pending = self.0.pending.lock().unwrap();
        pending.value = Some(value);
        if !pending.scheduled {
            pending.scheduled = true;
            let _ = self.0.notify.try_send(());
        }
    }
}
impl Worker {
    pub fn start<T: Send + 'static>(
        name: &str,
        on_update: impl FnMut(T) + 'static,
        run: impl FnOnce(UnixStream, Updates<T>) + Send + 'static,
    ) -> io::Result<Self> {
        let (stop, listener) = UnixStream::pair()?;
        #[allow(deprecated)]
        let (notify, rx) = glib::MainContext::sync_channel(glib::Priority::DEFAULT_IDLE, 1);
        let latest = Arc::new(Latest {
            pending: Mutex::new(Mailbox {
                value: None,
                scheduled: false,
            }),
            notify,
        });
        let updates = Updates(latest.clone());
        let worker = thread::Builder::new()
            .name(name.into())
            .spawn(move || run(listener, updates))?;
        // GLib's channel dispatch drains until empty. If a producer writes faster
        // than GTK renders, resetting `scheduled` in that callback can monopolize
        // a whole main-loop iteration. Drain only the latest value on a separate
        // bounded timer; quiet widgets have no timer at all.
        let timer = Rc::new(RefCell::new(None));
        let active_timer = timer.clone();
        let on_update = Rc::new(RefCell::new(on_update));
        let source = rx.attach(None, move |_| {
            let latest = latest.clone();
            let active = active_timer.clone();
            let on_update = on_update.clone();
            *active_timer.borrow_mut() = Some(glib::timeout_add_local_once(
                Duration::from_millis(16),
                move || {
                    active.borrow_mut().take();
                    let value = {
                        let mut pending = latest.pending.lock().unwrap();
                        pending.scheduled = false;
                        pending.value.take()
                    };
                    if let Some(value) = value {
                        (on_update.borrow_mut())(value);
                    }
                },
            ));
            glib::ControlFlow::Continue
        });
        Ok(Self {
            stop: Some(stop),
            source: Some(source),
            timer,
            thread: Some(worker),
        })
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.shutdown(std::net::Shutdown::Both);
        } // Wakes poll even if the producer has been silent for hours.
        if let Some(id) = self.timer.borrow_mut().take() {
            id.remove();
        }
        if let Some(id) = self.source.take() {
            id.remove();
        }
        if let Some(handle) = self.thread.take() {
            let _ = handle.join();
        }
    }
}

fn ready(stop: &UnixStream, fd: RawFd, ms: i32) -> io::Result<bool> {
    let mut fds = [
        libc::pollfd {
            fd: stop.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        },
        libc::pollfd {
            fd,
            events: libc::POLLIN,
            revents: 0,
        },
    ];
    loop {
        // Both descriptors are owned by the caller for the whole poll.
        let rc = unsafe { libc::poll(fds.as_mut_ptr(), 2, ms) };
        if rc >= 0 {
            return Ok(fds[0].revents == 0);
        }
        let err = io::Error::last_os_error();
        if err.kind() != io::ErrorKind::Interrupted {
            return Err(err);
        }
    }
}
pub(super) fn delay(stop: &UnixStream, duration: Duration) -> bool {
    ready(stop, -1, duration.as_millis().min(i32::MAX as u128) as i32).unwrap_or(false)
}

pub(super) fn lines(
    input: &mut (impl Read + AsRawFd),
    stop: &UnixStream,
    mut on_line: impl FnMut(&[u8]),
) -> io::Result<bool> {
    const LIMIT: usize = 1 << 20;
    let mut buf = [0u8; 16384];
    let mut line = Vec::new();
    let mut oversized = false;
    loop {
        if !ready(stop, input.as_raw_fd(), -1)? {
            return Ok(false);
        }
        let len = match input.read(&mut buf) {
            Ok(len) => len,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };
        if len == 0 {
            if !oversized && !line.is_empty() {
                on_line(&line);
            }
            return Ok(true);
        }
        for chunk in buf[..len].split_inclusive(|&b| b == b'\n') {
            let complete = chunk.ends_with(b"\n");
            let body = if complete {
                &chunk[..chunk.len() - 1]
            } else {
                chunk
            };
            if !oversized {
                if line.len() + body.len() > LIMIT {
                    line.clear();
                    oversized = true;
                } else {
                    line.extend_from_slice(body);
                }
            }
            if complete {
                if !oversized {
                    on_line(line.strip_suffix(b"\r").unwrap_or(&line));
                }
                line.clear();
                oversized = false;
            }
        }
    }
}

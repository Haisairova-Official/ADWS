use std::collections::HashMap;

use niri_ipc::{Action, Output, Reply, Request, socket::Socket};
pub use state::{Snapshot, Window};
#[cfg(test)]
pub use state::WindowSet;
pub use window_stream::WindowStream;

use crate::error::Error;

mod reply;
mod state;
mod window_stream;

/// The top level client for Niri.
#[derive(Debug, Clone, Copy)]
pub struct Niri {}

impl Niri {
    pub fn new() -> Self {
        // Since niri_ipc is essentially stateless, we don't maintain anything much here.
        Self {}
    }

    /// Requests that the given window ID should be activated.
    #[tracing::instrument(level = "TRACE", err)]
    pub fn activate_window(&self, id: u64) -> Result<(), Error> {
        let reply = request(Request::Action(Action::FocusWindow { id }))?;
        reply::typed!(Handled, reply)
    }

    /// Keep compositor round trips off GTK. A single worker retains only the
    /// latest pending focus, so rapid clicks never build an unbounded backlog.
    pub fn activate_window_background(&self, id: u64) {
        use std::sync::{LazyLock, Mutex, mpsc};
        static PENDING: Mutex<Option<u64>> = Mutex::new(None);
        static WORKER: LazyLock<mpsc::SyncSender<()>> = LazyLock::new(|| {
            let (tx, rx) = mpsc::sync_channel(1);
            std::thread::Builder::new().name("adws-window-focus".into()).spawn(move || {
                while rx.recv().is_ok() {
                    let id = PENDING.lock().expect("focus queue").take();
                    if let Some(id) = id {
                        if let Err(error) = Niri::new().activate_window(id) {
                            tracing::warn!(%error, id, "window activation failed");
                        }
                    }
                }
            }).expect("focus worker");
            tx
        });
        *PENDING.lock().expect("focus queue") = Some(id);
        let _ = WORKER.try_send(());
    }

    /// Requests that the given window ID should be closed.
    #[tracing::instrument(level = "TRACE", err)]
    pub fn close_window(&self, id: u64) -> Result<(), Error> {
        let reply = request(Request::Action(Action::CloseWindow { id: Some(id) }))?;
        reply::typed!(Handled, reply)
    }

    /// Force-terminate the process owning this window; one process may own several windows.
    pub fn terminate_window(&self, id: u64) {
        std::thread::spawn(move || {
            let result = (|| -> Result<(), Error> {
                let windows: Vec<niri_ipc::Window> = reply::typed!(Windows, request(Request::Windows)?)?;
                let pid = windows.iter().find(|w| w.id == id).and_then(|w| w.pid)
                    .filter(|pid| *pid > 1 && *pid as u32 != std::process::id())
                    .ok_or_else(|| Error::NiriReply("Window has no safe process ID".into()))?;
                let status = std::process::Command::new("kill").args(["-KILL", "--", &pid.to_string()])
                    .status().map_err(Error::NiriIpc)?;
                if !status.success() { return Err(Error::NiriReply("Process termination failed".into())); }
                tracing::info!(id, pid, "Window process terminated");
                Ok(())
            })();
            if let Err(error)=result { tracing::warn!(id, %error, "Window termination failed"); }
        });
    }

    /// Toggles the minimized state of the given window ID.
    #[tracing::instrument(level = "TRACE", err)]
    pub fn toggle_window_minimized(&self, id: u64) -> Result<(), Error> {
        let reply = request(Request::Action(Action::ToggleWindowMinimized { id: Some(id) }))?;
        if let Err(message) = &reply {
            if message.contains("unknown variant") && message.contains("ToggleWindowMinimized") {
                // Upstream Niri has no minimization action; focusing is universally supported.
                return self.activate_window(id);
            }
        }
        reply::typed!(Handled, reply)
    }

    /// Returns the current outputs.
    pub fn outputs(&self) -> Result<HashMap<String, Output>, Error> {
        let reply = request(Request::Outputs)?;
        reply::typed!(Outputs, reply)
    }

    /// Returns a stream of window snapshots.
    pub fn window_stream(&self, current_workspace_only: bool) -> WindowStream {
        WindowStream::new(current_workspace_only)
    }


}

// Helper to marshal request errors into our own type system.
//
// This can't be used for event streams, since the stream callback is thrown away in this function.
#[tracing::instrument(level = "TRACE", err)]
fn request(request: Request) -> Result<Reply, Error> {
    let action = matches!(&request, Request::Action(_));
    if action { tracing::info!(?request, "{}", crate::i18n::text("窗口操作请求", "Window action requested")); }
    let result = socket().and_then(|mut socket| {
        // This is the one-shot transport only; the event stream remains open.
        let transport = socket.try_clone_stream().map_err(Error::NiriIpc)?;
        transport.set_read_timeout(Some(std::time::Duration::from_secs(2))).map_err(Error::NiriIpc)?;
        transport.set_write_timeout(Some(std::time::Duration::from_secs(2))).map_err(Error::NiriIpc)?;
        socket.send(request).map_err(Error::NiriIpc)
    });
    if action {
        match &result {
            Ok(reply) => tracing::info!(?reply, "{}", crate::i18n::text("窗口操作响应", "Window action response")),
            Err(error) => tracing::error!(%error, "{}", crate::i18n::text("窗口操作失败", "Window action failed")),
        }
    }
    result
}

// Helper to connect to the Niri socket.
#[tracing::instrument(level = "TRACE", err)]
fn socket() -> Result<Socket, Error> {
    Socket::connect().map_err(Error::NiriIpc)
}

#[cfg(test)]
mod focus_tests {
    #[test]
    #[ignore = "changes fixture NIRI_SOCKET; run in isolation"]
    fn delayed_focus_does_not_block_caller_and_coalesces_pending_clicks() {
        use std::{io::{BufRead, BufReader, Write}, os::unix::net::UnixListener,
                  sync::mpsc, time::{Duration, Instant}};
        let path=std::env::temp_dir().join(format!("adws-focus-{}.sock",std::process::id()));
        let listener=UnixListener::bind(&path).unwrap();
        let old=std::env::var_os("NIRI_SOCKET");
        unsafe { std::env::set_var("NIRI_SOCKET",&path); }
        let (tx,rx)=mpsc::channel();
        let server=std::thread::spawn(move || {
            for expected in [101,103] {
                let (mut socket,_)=listener.accept().unwrap();
                socket.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
                let mut line=String::new();
                BufReader::new(socket.try_clone().unwrap()).read_line(&mut line).unwrap();
                let value:serde_json::Value=serde_json::from_str(&line).unwrap();
                assert_eq!(value["Action"]["FocusWindow"]["id"],expected);
                tx.send(expected).unwrap();
                std::thread::sleep(Duration::from_millis(250));
                writeln!(socket,"{}",serde_json::json!({"Ok":"Handled"})).unwrap();
            }
        });
        let niri=super::Niri::new();
        let started=Instant::now();
        niri.activate_window_background(101);
        assert!(started.elapsed()<Duration::from_millis(100),"caller waited for compositor");
        assert_eq!(rx.recv_timeout(Duration::from_secs(2)).unwrap(),101);
        niri.activate_window_background(102);
        niri.activate_window_background(103);
        assert_eq!(rx.recv_timeout(Duration::from_secs(2)).unwrap(),103);
        server.join().unwrap();
        unsafe { if let Some(old)=old {std::env::set_var("NIRI_SOCKET",old);} else {std::env::remove_var("NIRI_SOCKET");} }
        std::fs::remove_file(path).unwrap();
    }
}

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
    let result = socket().and_then(|mut socket| socket.send(request).map_err(Error::NiriIpc));
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

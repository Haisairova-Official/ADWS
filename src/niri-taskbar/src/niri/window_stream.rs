use async_channel::{Receiver, Sender};
use niri_ipc::Request;

use crate::error::Error;

use super::{
    reply, socket,
    state::{Snapshot, WindowSet},
};

/// A stream that receives events from Niri and produces a stream of window [`Snapshot`]s.
pub struct WindowStream {
    rx: Receiver<Snapshot>,
}

impl WindowStream {
    pub(super) fn new(current_workspace_only: bool) -> Self {
        let (tx, rx) = async_channel::unbounded();
        std::thread::spawn(move || {
            while !tx.is_closed() {
                if let Err(e) = window_stream(tx.clone(), current_workspace_only) {
                    tracing::error!(%e, "Niri taskbar window stream error; reconnecting");
                }
                if tx.is_closed() { break; }
                std::thread::sleep(std::time::Duration::from_secs(2));
            }
        });

        Self { rx }
    }

    /// Awaits the next [`Snapshot`].
    pub async fn next(&self) -> Option<Snapshot> {
        self.rx.recv().await.ok()
    }
}

fn window_stream(tx: Sender<Snapshot>, current_workspace_only: bool) -> Result<(), Error> {
    let mut socket = socket()?;
    let reply = socket.send(Request::EventStream).map_err(Error::NiriIpc)?;
    reply::typed!(Handled, reply)?;
    let mut next = socket.read_events();

    let mut state = WindowSet::new(current_workspace_only);
    loop {
        // There appears to be no EOF state, presumably on the assumption that if Niri goes away it
        // doesn't matter what happens to this process.
        match next() {
            Ok(event) => {
                if let Some(snapshot) = state.with_event(event) {
                    tx.send_blocking(snapshot)
                        .map_err(|_| Error::WindowStreamSend)?;
                }
            }
            Err(e) => {
                if e.kind() == std::io::ErrorKind::InvalidData {
                    tracing::warn!(%e, "Ignoring unsupported or malformed Niri event");
                    continue;
                }
                tracing::error!(%e, "Niri IPC error reading from event stream");
                return Err(Error::NiriIpc(e));
            }
        }
    }
}

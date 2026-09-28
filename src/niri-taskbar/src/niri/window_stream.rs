use async_channel::{Receiver, Sender};
use niri_ipc::{Event, Request};

use crate::error::Error;

use super::{
    reply, socket,
    state::{Snapshot, WindowSet},
};

/// A stream that receives events from Niri and produces a stream of window [`Snapshot`]s.
pub struct WindowStream {
    rx: Receiver<(Snapshot, bool)>,
}

impl WindowStream {
    pub(super) fn new(current_workspace_only: bool) -> Self {
        let (tx, rx) = async_channel::unbounded();
        std::thread::spawn(move || {
            let mut reconnect = false;
            while !tx.is_closed() {
                if let Err(e) = window_stream(tx.clone(), current_workspace_only, reconnect) {
                    tracing::error!(%e, "Niri taskbar window stream error; reconnecting");
                }
                reconnect = true;
                if tx.is_closed() { break; }
                std::thread::sleep(std::time::Duration::from_secs(2));
            }
        });

        Self { rx }
    }

    /// Awaits the next [`Snapshot`].
    pub async fn next(&self) -> Option<(Snapshot, bool)> {
        self.rx.recv().await.ok()
    }
}

fn window_stream(tx: Sender<(Snapshot, bool)>, current_workspace_only: bool, reconnect: bool) -> Result<(), Error> {
    let mut socket = socket()?;
    let reply = socket.send(Request::EventStream).map_err(Error::NiriIpc)?;
    reply::typed!(Handled, reply)?;
    let mut next = socket.read_events();

    let mut state = WindowSet::new(current_workspace_only);
    let mut updates = WindowUpdates::new(reconnect);
    loop {
        // There appears to be no EOF state, presumably on the assumption that if Niri goes away it
        // doesn't matter what happens to this process.
        match next() {
            Ok(event) => {
                updates.observe(&event);
                if let Some(snapshot) = state.with_event(event) {
                    tx.send_blocking((snapshot, std::mem::take(&mut updates.outputs_changed)))
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

// Track output topology independently of event ordering and reconnects.
#[derive(Default)]
struct WindowUpdates {
    outputs: Option<std::collections::BTreeSet<String>>,
    outputs_changed: bool,
}
impl WindowUpdates {
    fn new(reconnect: bool) -> Self { Self { outputs_changed: reconnect, ..Self::default() } }
    fn observe(&mut self, event: &Event) {
        if let Event::WorkspacesChanged { workspaces } = event {
            let names = workspaces.iter().filter_map(|w| w.output.clone()).collect();
            self.outputs_changed |= self.outputs.as_ref().is_some_and(|old| old != &names);
            self.outputs = Some(names);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn workspaces(outputs: &[&str]) -> Event {
        serde_json::from_value(serde_json::json!({"WorkspacesChanged": {"workspaces":
            outputs.iter().enumerate().map(|(i, output)| serde_json::json!({
                "id": i+1, "idx": i+1, "name": null, "output": output,
                "is_urgent": false, "is_active": true, "is_focused": i==0,
                "active_window_id": null
            })).collect::<Vec<_>>()
        }})).unwrap()
    }
    #[test]
    fn topology_refresh_ignores_workspace_churn_but_survives_reconnect() {
        let mut updates = WindowUpdates::new(false);
        updates.observe(&workspaces(&["DP-1"]));
        assert!(!updates.outputs_changed); // initial filter already loaded
        updates.observe(&workspaces(&["DP-1", "DP-1"]));
        assert!(!updates.outputs_changed); // new workspace, same physical output
        updates.observe(&workspaces(&["DP-1", "DP-2"]));
        updates.observe(&Event::WindowsChanged { windows: vec![] });
        assert!(std::mem::take(&mut updates.outputs_changed));
        updates.observe(&workspaces(&["DP-2", "DP-1"]));
        assert!(!updates.outputs_changed);
        updates.observe(&workspaces(&["DP-1"]));
        assert!(updates.outputs_changed); // unplug
        let mut reconnect = WindowUpdates::new(true);
        reconnect.observe(&workspaces(&["DP-1"]));
        assert!(reconnect.outputs_changed); // topology may change while disconnected
    }
}

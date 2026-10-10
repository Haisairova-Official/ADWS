use async_channel::{Receiver, Sender};
use niri_ipc::{Event, Request};
use std::sync::{Arc, Mutex};
use std::{net::Shutdown, os::unix::net::UnixStream};

use crate::error::Error;

use super::{
    reply, socket,
    state::{Snapshot, WindowSet},
};

/// A stream that receives events from Niri and produces a stream of window [`Snapshot`]s.
pub struct WindowStream {
    rx: Receiver<()>,
    pending: Arc<Mutex<Option<(Snapshot, bool)>>>,
    socket: Arc<Mutex<Option<UnixStream>>>,
}

struct SnapshotSender {
    tx: Sender<()>,
    pending: Arc<Mutex<Option<(Snapshot, bool)>>>,
    socket: Arc<Mutex<Option<UnixStream>>>,
}

impl SnapshotSender {
    fn publish(&self, snapshot: Snapshot, outputs_changed: bool) -> Result<(), Error> {
        {
            let mut pending = self.pending.lock().expect("pending window snapshot");
            let changed = outputs_changed || pending.as_ref().is_some_and(|(_, changed)| *changed);
            // Every IPC event is applied to WindowSet. Only obsolete UI snapshots
            // are replaced; topology changes remain sticky until consumed.
            *pending = Some((snapshot, changed));
        }
        match self.tx.try_send(()) {
            Ok(()) | Err(async_channel::TrySendError::Full(())) => Ok(()),
            Err(async_channel::TrySendError::Closed(())) => Err(Error::WindowStreamSend),
        }
    }
}

impl Drop for WindowStream {
    fn drop(&mut self) {
        self.rx.close();
        if let Some(socket) = self.socket.lock().expect("event socket").take() {
            let _ = socket.shutdown(Shutdown::Both);
        }
    }
}

impl WindowStream {
    fn channel() -> (SnapshotSender, Self) {
        let (tx, rx) = async_channel::bounded(1);
        let pending = Arc::new(Mutex::new(None));
        let socket = Arc::new(Mutex::new(None));
        (SnapshotSender { tx, pending: pending.clone(), socket: socket.clone() }, Self { rx, pending, socket })
    }

    pub(super) fn new(current_workspace_only: bool) -> Self {
        let (sender, stream) = Self::channel();
        std::thread::spawn(move || {
            let mut reconnect = false;
            while !sender.tx.is_closed() {
                if let Err(e) = window_stream(&sender, current_workspace_only, reconnect) {
                    if sender.tx.is_closed() { break; }
                    tracing::error!(%e, "Niri taskbar window stream error; reconnecting");
                }
                sender.socket.lock().expect("event socket").take();
                reconnect = true;
                if sender.tx.is_closed() { break; }
                std::thread::sleep(std::time::Duration::from_secs(2));
            }
        });

        stream
    }

    /// Awaits the next [`Snapshot`].
    pub async fn next(&self) -> Option<(Snapshot, bool)> {
        while self.rx.recv().await.is_ok() {
            if let Some(snapshot) = self.pending.lock().expect("pending window snapshot").take() {
                return Some(snapshot);
            }
            // A producer may have signalled after its value was already consumed.
        }
        None
    }
}

fn window_stream(sender: &SnapshotSender, current_workspace_only: bool, reconnect: bool) -> Result<(), Error> {
    read_socket(sender, current_workspace_only, reconnect, socket()?)
}

fn read_socket(sender: &SnapshotSender, current_workspace_only: bool, reconnect: bool,
               mut socket: niri_ipc::socket::Socket) -> Result<(), Error> {
    {
        let mut transport = sender.socket.lock().expect("event socket");
        if sender.tx.is_closed() { return Err(Error::WindowStreamSend); }
        *transport = Some(socket.try_clone_stream().map_err(Error::NiriIpc)?);
    }
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
                    sender.publish(snapshot, std::mem::take(&mut updates.outputs_changed))?;
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
    #[test]
    fn slow_ui_keeps_one_latest_snapshot_and_preserves_topology_change() {
        let (sender, stream) = WindowStream::channel();
        let mut state = WindowSet::new(false);
        state.with_event(workspaces(&["DP-1"]));
        let window = serde_json::json!({
            "id":1, "title":"old", "app_id":"test", "pid":null,
            "workspace_id":1, "is_focused":true, "is_floating":false,
            "is_urgent":false, "focus_timestamp":null,
            "layout":{"pos_in_scrolling_layout":[1,1], "tile_size":[800.0,600.0],
                "window_size":[800,600], "tile_pos_in_workspace_view":[0.0,0.0],
                "window_offset_in_tile":[0.0,0.0]}
        });
        let snapshot = state.with_event(serde_json::from_value(serde_json::json!({
            "WindowsChanged":{"windows":[window]}
        })).unwrap()).unwrap();
        // Simulate a UI that does not consume anything throughout a long burst.
        for i in 0..100_000 {
            sender.publish(snapshot.clone(), i == 50).unwrap();
        }
        // The latest state closes the window; replaying old snapshots is wrong.
        sender.publish(Vec::new(), false).unwrap();
        assert_eq!(stream.rx.len(), 1);
        let (latest, changed) = futures::executor::block_on(stream.next()).unwrap();
        assert!(latest.is_empty());
        assert!(changed);
        sender.publish(snapshot, false).unwrap();
        assert!(!futures::executor::block_on(stream.next()).unwrap().1);
        drop(stream);
        assert!(sender.tx.is_closed());
        assert!(sender.publish(Vec::new(), false).is_err());
    }

    #[test]
    fn concurrent_producer_does_not_lose_final_wakeup() {
        let (sender, stream) = WindowStream::channel();
        let worker = std::thread::spawn(move || {
            for _ in 0..100_000 { sender.publish(Vec::new(), false).unwrap(); }
            sender.publish(Vec::new(), true).unwrap();
        });
        let mut final_seen = false;
        futures::executor::block_on(async {
            while let Some((_, changed)) = stream.next().await { final_seen |= changed; }
        });
        worker.join().unwrap();
        assert!(final_seen);
    }
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

#[cfg(test)]
mod shutdown_tests {
    use super::*;
    use std::{io::{BufRead, BufReader, Write}, os::unix::net::UnixListener, time::Duration};
    #[test]
    fn dropping_stream_interrupts_idle_socket_read() {
        let path=std::env::temp_dir().join(format!("adws-idle-reader-{}.sock",std::process::id()));
        let listener=UnixListener::bind(&path).unwrap();
        let client=niri_ipc::socket::Socket::connect_to(&path).unwrap();
        let (mut server,_)=listener.accept().unwrap();
        server.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let (sender,stream)=WindowStream::channel();
        let (done_tx,done_rx)=std::sync::mpsc::channel();
        let worker=std::thread::spawn(move || {
            let result=read_socket(&sender,false,false,client);
            done_tx.send(result.is_err()).unwrap();
        });
        let mut request=String::new();
        BufReader::new(server.try_clone().unwrap()).read_line(&mut request).unwrap();
        assert!(request.contains("EventStream"));
        writeln!(server,"{{\"Ok\":\"Handled\"}}").unwrap();
        // No further event is sent. Cancellation must not wait for one.
        drop(stream);
        assert!(done_rx.recv_timeout(Duration::from_secs(1)).unwrap());
        worker.join().unwrap();
        std::fs::remove_file(path).unwrap();
    }
}

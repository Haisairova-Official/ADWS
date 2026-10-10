use std::sync::Arc;

use async_channel::Sender;
use futures::{Stream, StreamExt};
use waybar_cffi::gtk::glib;

use crate::{
    config::Config,
    error::Error,
    icon,
    niri::{Niri, Snapshot, WindowStream},
    notify::{self, EnrichedNotification},
};

/// Global state for the taskbar.
#[derive(Debug, Clone)]
pub struct State(Arc<Inner>);

impl State {
    /// Instantiates the global state.
    pub fn new(config: Config) -> Self {
        Self(Arc::new(Inner {
            config,
            icon_cache: icon::Cache::default(),
            niri: Niri::new(),
        }))
    }

    /// Returns the taskbar configuration.
    pub fn config(&self) -> &Config {
        &self.0.config
    }

    /// Accesses the global icon cache.
    pub fn icon_cache(&self) -> &icon::Cache {
        &self.0.icon_cache
    }

    /// Accesses the global [`Niri`] instance.
    pub fn niri(&self) -> &Niri {
        &self.0.niri
    }

    pub fn event_stream(&self) -> Result<impl Stream<Item = Event> + use<>, Error> {
        // Backpressure here must reach WindowStream's latest-state mailbox;
        // an unbounded second queue would merely move the snapshot backlog.
        let (tx, rx) = async_channel::bounded(1);

        let mut tasks = crate::tasks::Tasks::default();
        if self.config().notifications_enabled() {
            tasks.0.push(glib::spawn_future_local(notify_stream(tx.clone())));
        }

        tasks.0.push(glib::spawn_future_local(window_stream(
            tx.clone(),
            self.niri().window_stream(false),
        )));

        tasks.0.push(glib::spawn_future_local(crate::pins::watch(tx.clone())));

        // All socket reads belong to the single background window stream.
        Ok(async_stream::stream! {
            let _tasks = tasks;
            while let Ok(event) = rx.recv().await {
                yield event;
                // A ready channel does not yield the executor. Give input,
                // drawing and timers a turn even under a continuous event flood.
                glib::timeout_future(std::time::Duration::from_millis(1)).await;
            }
        })
    }
}

#[derive(Debug)]
struct Inner {
    config: Config,
    icon_cache: icon::Cache,
    niri: Niri,
}

pub enum Event {
    Notification(Box<EnrichedNotification>),
    WindowSnapshot(Snapshot),
    Workspaces(()),
    PinsChanged(Vec<crate::pins::Pin>),
}

async fn notify_stream(tx: Sender<Event>) {
    let mut stream = Box::pin(notify::stream());

    while let Some(notification) = stream.next().await {
        if let Err(e) = tx.send(Event::Notification(Box::new(notification))).await {
            tracing::error!(%e, "error sending notification");
            break;
        }
    }
}

async fn window_stream(tx: Sender<Event>, window_stream: WindowStream) {
    while let Some((snapshot, outputs_changed)) = window_stream.next().await {
        if outputs_changed && tx.send(Event::Workspaces(())).await.is_err() { break; }
        if let Err(e) = tx.send(Event::WindowSnapshot(snapshot)).await {
            tracing::error!(%e, "error sending window snapshot");
            break;
        }
    }
}

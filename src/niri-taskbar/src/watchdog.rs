//! Observe GTK from a separate thread: a stuck main loop cannot check itself.
use std::{path::PathBuf, sync::{Arc, atomic::{AtomicU64, Ordering}}, time::{Duration, Instant}};

#[derive(Default)]
struct Monitor { previous: u64, missed: u32 }
impl Monitor {
    fn sample(&mut self, beat: u64, elapsed: Duration) -> bool {
        // Resume/system-wide scheduling pauses are not a frozen taskbar.
        if beat != self.previous || elapsed > Duration::from_secs(3) {
            self.missed = 0;
        } else {
            self.missed += 1;
        }
        self.previous = beat;
        self.missed >= 10
    }
}

pub fn start(helper: Option<PathBuf>) -> Arc<AtomicU64> {
    let heartbeat = Arc::new(AtomicU64::new(0));
    if std::env::var("ADWS_TASKBAR_WATCHDOG").as_deref() == Ok("0") { return heartbeat; }
    let Some(helper) = helper else { return heartbeat; };
    let beat = heartbeat.clone();
    std::thread::spawn(move || {
        let mut monitor = Monitor::default();
        let mut previous = Instant::now();
        loop {
            std::thread::sleep(Duration::from_secs(1));
            let now = Instant::now();
            let hung = monitor.sample(beat.load(Ordering::Relaxed), now.duration_since(previous));
            previous = now;
            if hung {
                tracing::error!("ADWS taskbar unresponsive for 10 seconds; requesting diagnostic recovery");
                match std::process::Command::new("python3").arg(&helper)
                    .arg(std::process::id().to_string()).spawn() {
                    Ok(mut child) => { let _ = child.wait(); },
                    Err(error) => tracing::error!(%error, "could not start taskbar recovery"),
                }
                // Exactly one attempt per instance, including rate-limit rejection.
                break;
            }
        }
    });
    heartbeat
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn requires_continuous_stall_and_ignores_suspend() {
        let mut m = Monitor::default();
        for _ in 0..9 { assert!(!m.sample(0, Duration::from_secs(1))); }
        assert!(!m.sample(0, Duration::from_secs(20)));
        for _ in 0..9 { assert!(!m.sample(0, Duration::from_secs(1))); }
        assert!(!m.sample(1, Duration::from_secs(1)));
        for _ in 0..9 { assert!(!m.sample(1, Duration::from_secs(1))); }
        assert!(m.sample(1, Duration::from_secs(1)));
    }
}

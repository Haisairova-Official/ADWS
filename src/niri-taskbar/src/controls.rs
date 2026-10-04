//! Taskbar controls: bounded asynchronous reads and coalesced wheel writes.
use crate::{config::Config, tasks::Tasks};
use std::{
    cell::{Cell, RefCell},
    ffi::OsStr,
    rc::Rc,
    time::Duration,
};
use waybar_cffi::gtk::{self, gio, glib, prelude::*};

pub(crate) struct Controls {
    _tasks: RefCell<Tasks>,
    child: RefCell<Option<gio::Subprocess>>,
    pub button: gtk::Button,
    pending: Cell<i32>,
    smooth: Cell<f64>,
    wheel_child: RefCell<Option<gio::Subprocess>>,
}
impl Drop for Controls {
    fn drop(&mut self) {
        if let Some(child) = self.child.borrow_mut().take() {
            child.force_exit();
        }
        if let Some(child) = self.wheel_child.borrow_mut().take() {
            child.force_exit();
        }
    }
}
impl Controls {
    pub fn new(root: &gtk::Container, config: &Config) -> Rc<Self> {
        let kind = config.component().to_owned();
        let helper = config.control_helper().to_owned();
        let output = config.control_output().to_owned();
        let edge = config.position().to_owned();
        let thickness = config.thickness();
        let button = gtk::Button::new();
        button.set_relief(gtk::ReliefStyle::None);
        button.style_context().add_class("adws-quick-button");
        let image = gtk::Image::from_icon_name(
            Some(if kind == "sound" {
                "audio-volume-high-symbolic"
            } else {
                "display-brightness-symbolic"
            }),
            gtk::IconSize::Button,
        );
        image.set_pixel_size((thickness as i32 - 14).clamp(16, 32));
        button.add(&image);
        button.set_tooltip_text(Some(crate::i18n::text(
            if kind == "sound" { "声音" } else { "亮度" },
            if kind == "sound" {
                "Sound"
            } else {
                "Brightness"
            },
        )));
        root.add(&button);
        button.show_all();
        let state = Rc::new(Self {
            _tasks: RefCell::new(Tasks::default()),
            child: RefCell::new(None),
            button: button.clone(),
            pending: Cell::new(0),
            smooth: Cell::new(0.0),
            wheel_child: RefCell::new(None),
        });
        let weak = Rc::downgrade(&state);
        let h = helper.clone();
        let k = kind.clone();
        let o = output.clone();
        state
            ._tasks
            .borrow_mut()
            .0
            .push(glib::spawn_future_local(async move {
                loop {
                    let Some(s) = weak.upgrade() else { break };
                    if let Ok(child) = gio::Subprocess::newv(
                        &[
                            OsStr::new("python3"),
                            OsStr::new(&h),
                            OsStr::new(&k),
                            OsStr::new("--status"),
                            OsStr::new("--output"),
                            OsStr::new(&o),
                        ],
                        gio::SubprocessFlags::STDOUT_PIPE | gio::SubprocessFlags::STDERR_SILENCE,
                    ) {
                        s.child.replace(Some(child.clone()));
                        drop(s);
                        let reply = child.communicate_utf8_future(None).await;
                        let Some(s) = weak.upgrade() else {
                            child.force_exit();
                            break;
                        };
                        s.child.borrow_mut().take();
                        if let Ok((Some(text), _)) = reply
                            && let Ok(value) = serde_json::from_str::<serde_json::Value>(&text)
                        {
                            if let Some(icon) = value["icon"].as_str() {
                                image.set_from_icon_name(Some(icon), gtk::IconSize::Button);
                            }
                            let label = crate::i18n::text(
                                if k == "sound" { "声音" } else { "亮度" },
                                if k == "sound" { "Sound" } else { "Brightness" },
                            );
                            button.set_tooltip_text(Some(&format!(
                                "{} · {}",
                                label,
                                value["text"].as_str().unwrap_or("—")
                            )));
                        }
                    } else {
                        drop(s);
                    }
                    glib::timeout_future(Duration::from_secs(5)).await;
                }
            }));
        let h = helper.clone();
        let k = kind.clone();
        let e = edge.clone();
        let o = output.clone();
        state
            .button
            .connect_button_press_event(move |button, event| {
                if !matches!(event.button(), 1 | 3) {
                    return glib::Propagation::Proceed;
                }
                let anchor = anchor(button, &e, thickness);
                let mut command = std::process::Command::new("python3");
                command
                    .arg(&h)
                    .arg(&k)
                    .arg("--output")
                    .arg(&o)
                    .arg("--anchor")
                    .arg(anchor);
                if event.button() == 3 {
                    command.arg("--panel");
                }
                // Spawn is short and never waits for settings/device services.
                if let Ok(mut child) = command.spawn() {
                    std::thread::spawn(move || {
                        let _ = child.wait();
                    });
                }
                glib::Propagation::Stop
            });
        state
            .button
            .add_events(gtk::gdk::EventMask::SCROLL_MASK | gtk::gdk::EventMask::SMOOTH_SCROLL_MASK);
        let weak = Rc::downgrade(&state);
        state.button.connect_scroll_event(move |_, event| {
            let Some(s) = weak.upgrade() else {
                return glib::Propagation::Proceed;
            };
            let (_, dy) = event.delta();
            let delta = wheel_delta(event.direction(), dy, &s.smooth);
            s.pending.set((s.pending.get() + delta).clamp(-100, 100));
            glib::Propagation::Stop
        });
        let weak = Rc::downgrade(&state);
        state
            ._tasks
            .borrow_mut()
            .0
            .push(glib::spawn_future_local(async move {
                loop {
                    glib::timeout_future(Duration::from_millis(100)).await;
                    let Some(s) = weak.upgrade() else { break };
                    let delta = s.pending.replace(0);
                    drop(s);
                    if delta == 0 {
                        continue;
                    }
                    if let Ok(child) = gio::Subprocess::newv(
                        &[
                            OsStr::new("python3"),
                            OsStr::new(&helper),
                            OsStr::new(&kind),
                            OsStr::new("--step"),
                            OsStr::new(&delta.to_string()),
                            OsStr::new("--output"),
                            OsStr::new(&output),
                        ],
                        gio::SubprocessFlags::STDERR_SILENCE,
                    ) {
                        // One wheel write at a time; new wheel deltas accumulate.
                        if let Some(s) = weak.upgrade() {
                            s.wheel_child.replace(Some(child.clone()));
                        }
                        let _ = child.wait_future().await;
                        if let Some(s) = weak.upgrade() {
                            s.wheel_child.borrow_mut().take();
                        }
                    }
                }
            }));
        state
    }
}
fn anchor(button: &gtk::Button, edge: &str, thickness: u32) -> String {
    let display = button.display();
    let top = button.toplevel();
    let monitor = top
        .as_ref()
        .and_then(|t| t.window())
        .and_then(|w| display.monitor_at_window(&w));
    let (width, height, index) = monitor
        .map(|m| {
            let r = m.geometry();
            let index = (0..display.n_monitors())
                .find(|i| display.monitor(*i).as_ref() == Some(&m))
                .unwrap_or(0);
            (r.width(), r.height(), index)
        })
        .unwrap_or((1920, 1080, 0));
    let (x, y) = top
        .as_ref()
        .and_then(|t| button.translate_coordinates(t, 0, 0))
        .unwrap_or((width / 2, height / 2));
    // Layer shell exposes local bar coordinates. Horizontal bars fill the width;
    // vertical bars fill height, independently of GDK's unreliable global origin.
    serde_json::json!({"edge":edge,"x":x+button.allocated_width()/2,"y":y+button.allocated_height()/2,"inset":thickness+10,"monitor":index}).to_string()
}

fn wheel_delta(direction: gtk::gdk::ScrollDirection, dy: f64, remainder: &Cell<f64>) -> i32 {
    match direction {
        gtk::gdk::ScrollDirection::Up => 5,
        gtk::gdk::ScrollDirection::Down => -5,
        gtk::gdk::ScrollDirection::Smooth if dy.is_finite() => {
            let value = remainder.get() - dy.clamp(-20.0, 20.0);
            let steps = value.trunc();
            remainder.set(value - steps);
            (steps as i32) * 5
        }
        _ => 0,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn wheel_steps_accumulate_smooth_input() {
        let value = Cell::new(0.0);
        for _ in 0..3 {
            assert_eq!(
                wheel_delta(gtk::gdk::ScrollDirection::Smooth, -0.3, &value),
                0
            );
        }
        assert_eq!(
            wheel_delta(gtk::gdk::ScrollDirection::Smooth, -0.3, &value),
            5
        );
        assert_eq!(wheel_delta(gtk::gdk::ScrollDirection::Up, 0.0, &value), 5);
        assert_eq!(
            wheel_delta(gtk::gdk::ScrollDirection::Down, 0.0, &value),
            -5
        );
        assert_eq!(
            wheel_delta(gtk::gdk::ScrollDirection::Smooth, f64::NAN, &value),
            0
        );
    }
}

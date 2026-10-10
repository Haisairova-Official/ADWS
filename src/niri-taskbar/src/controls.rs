//! Taskbar controls: bounded asynchronous reads and coalesced wheel writes.
use crate::{config::Config, tasks::Tasks};
use std::{
    cell::{Cell, RefCell},
    ffi::OsStr,
    rc::Rc,
    time::Duration,
};
use waybar_cffi::gtk::{self, gio, glib, prelude::*};

fn control_indicator(kind: &str, thickness: u32) -> (gtk::Overlay, gtk::Image, gtk::Image) {
    let overlay = gtk::Overlay::new();
    let image = gtk::Image::from_icon_name(Some(if kind == "sound" {
        "audio-volume-high-symbolic"
    } else { "display-brightness-symbolic" }), gtk::IconSize::Button);
    let size = (thickness as i32 - 14).clamp(16, 32);
    image.set_pixel_size(size);
    overlay.add(&image);
    let warning = gtk::Image::from_icon_name(Some("dialog-warning-symbolic"), gtk::IconSize::Button);
    warning.set_pixel_size((size / 2).clamp(9, 14));
    // Draw the no-device question without the theme's dialog bubble/frame.
    warning.connect_draw(|widget, cr| {
        if widget.icon_name().as_deref() != Some("dialog-question-symbolic") {
            return glib::Propagation::Proceed;
        }
        let size = f64::from(widget.pixel_size().max(1));
        let color = widget.style_context().color(widget.state_flags());
        let _ = cr.save();
        cr.translate((f64::from(widget.allocated_width())-size)/2.0,
                     (f64::from(widget.allocated_height())-size)/2.0);
        cr.scale(size/16.0, size/16.0);
        cr.set_source_rgba(color.red().into(), color.green().into(), color.blue().into(), color.alpha().into());
        cr.set_line_width(2.0);
        cr.set_line_cap(gtk::cairo::LineCap::Round);
        cr.move_to(4.0, 4.5);
        cr.curve_to(4.0, 0.5, 12.0, 0.5, 12.0, 4.5);
        cr.curve_to(12.0, 8.0, 8.0, 7.5, 8.0, 10.5);
        let _ = cr.stroke();
        cr.arc(8.0, 14.0, 1.1, 0.0, std::f64::consts::TAU);
        let _ = cr.fill();
        let _ = cr.restore();
        glib::Propagation::Stop
    });
    warning.set_halign(gtk::Align::End);
    warning.set_valign(gtk::Align::End);
    warning.set_no_show_all(true);
    warning.style_context().add_class("adws-control-warning");
    overlay.add_overlay(&warning);
    overlay.set_overlay_pass_through(&warning, true);
    (overlay, image, warning)
}

fn apply_control_status(button: &gtk::Button, image: &gtk::Image, warning: &gtk::Image,
                        kind: &str, value: &serde_json::Value) {
    let icon = value["icon"].as_str();
    let error = value["error"].as_str().filter(|s| !s.is_empty());
    // Older helpers may still return a warning icon. Keep the last valid
    // component icon and express the failure through the small overlay only.
    let alert = value["available"].as_bool() == Some(false) || error.is_some()
        || icon.is_some_and(|s| s.starts_with("dialog-warning") || s.starts_with("dialog-error"));
    let no_device = kind == "sound" && value["state"].as_str() == Some("no-device");
    let size = image.pixel_size().max(16);
    let badge_size = if no_device { (size * 3 / 4).clamp(12, 24) } else { (size / 2).clamp(9, 14) };
    // The no-device question is a companion glyph, not a corner badge.
    image.set_margin_end(if no_device { badge_size.saturating_sub(5) } else { 0 });
    warning.set_pixel_size(badge_size);
    warning.set_valign(if no_device { gtk::Align::Center } else { gtk::Align::End });
    if no_device {
        image.set_from_icon_name(Some("audio-volume-muted-symbolic"), gtk::IconSize::Button);
        warning.set_from_icon_name(Some("dialog-question-symbolic"), gtk::IconSize::Button);
        warning.show();
    } else if alert {
        warning.set_from_icon_name(Some("dialog-warning-symbolic"), gtk::IconSize::Button);
        warning.show();
    }
    else {
        warning.hide();
        if let Some(icon) = icon { image.set_from_icon_name(Some(icon), gtk::IconSize::Button); }
    }
    let label = crate::i18n::text(if kind == "sound" { "声音" } else { "亮度" },
                               if kind == "sound" { "Sound" } else { "Brightness" });
    let mut tooltip = format!("{} · {}", label, value["text"].as_str().unwrap_or("—"));
    if let Some(error) = error { tooltip.push('\n'); tooltip.push_str(error); }
    if button.tooltip_text().as_deref() != Some(tooltip.as_str()) {
        button.set_tooltip_text(Some(&tooltip));
        button.trigger_tooltip_query();
    }
}

pub(crate) struct Controls {
    _tasks: RefCell<Tasks>,
    child: RefCell<Option<gio::Subprocess>>,
    pub button: gtk::Button,
    pending: Cell<i32>,
    smooth: Cell<f64>,
    wheel_child: RefCell<Option<gio::Subprocess>>,
    refresh: async_channel::Sender<()>,
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
        let (indicator, image, warning) = control_indicator(&kind, thickness);
        button.add(&indicator);
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
        // Coalesce clicks and writes into the existing status worker.
        let (refresh, refresh_requests) = async_channel::bounded(1);
        let state = Rc::new(Self {
            _tasks: RefCell::new(Tasks::default()),
            child: RefCell::new(None),
            button: button.clone(),
            pending: Cell::new(0),
            smooth: Cell::new(0.0),
            wheel_child: RefCell::new(None),
            refresh,
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
                        // A stuck helper must not stop all future status updates.
                        // DDC discovery can legitimately take longer than audio queries.
                        let expired = Rc::new(Cell::new(false));
                        let deadline_expired = expired.clone();
                        let deadline_child = child.clone();
                        let deadline = glib::timeout_add_local_once(
                            Duration::from_secs(if k == "sound" { 8 } else { 45 }),
                            move || { deadline_expired.set(true); deadline_child.force_exit(); },
                        );
                        let reply = child.communicate_utf8_future(None).await;
                        // SourceId::remove cannot be called after the deadline fired.
                        if !expired.get() {
                            deadline.remove();
                        }
                        let Some(s) = weak.upgrade() else {
                            child.force_exit();
                            break;
                        };
                        s.child.borrow_mut().take();
                        let value = reply.ok().and_then(|(text, _)| text)
                            .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
                            .filter(|value| value.is_object())
                            .unwrap_or_else(|| serde_json::json!({"available": false, "text": "—",
                                "error": crate::i18n::text("状态读取失败，将自动重试", "Status unavailable; retrying automatically")}));
                        apply_control_status(&button, &image, &warning, &k, &value);
                    } else {
                        drop(s);
                        apply_control_status(&button, &image, &warning, &k,
                            &serde_json::json!({"available": false, "text": "—",
                                "error": crate::i18n::text("无法启动状态查询，将自动重试", "Cannot start status query; retrying automatically")}));
                    }
                    let delay = glib::timeout_future(Duration::from_secs(if k == "sound" { 2 } else { 5 }));
                    let request = refresh_requests.recv();
                    futures::pin_mut!(delay, request);
                    if let futures::future::Either::Right((Err(_), _)) = futures::future::select(delay, request).await {
                        break;
                    }
                }
            }));
        let h = helper.clone();
        let k = kind.clone();
        let e = edge.clone();
        let o = output.clone();
        let refresh = state.refresh.clone();
        state
            .button
            .connect_button_press_event(move |button, event| {
                if !matches!(event.button(), 1 | 3) {
                    return glib::Propagation::Proceed;
                }
                let _ = refresh.try_send(());
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
                            let _ = s.refresh.try_send(());
                        }
                    }
                }
            }));
        state
    }
}
/// Sidebar has no polling workers: send the actual button monitor and geometry.
fn sidebar_service_missing(error: &glib::Error) -> bool {
    use glib::translate::{from_glib_full, ToGlibPtr};
    let remote: Option<glib::GString> = unsafe {
        from_glib_full(gio::ffi::g_dbus_error_get_remote_error(error.to_glib_none().0))
    };
    matches!(remote.as_deref(), Some("org.freedesktop.DBus.Error.ServiceUnknown" | "org.freedesktop.DBus.Error.NameHasNoOwner"))
}

async fn request_sidebar(helper: String, anchor: String, prepare: bool) {
    // A warm click talks to the service directly; no Python process/import on
    // the critical path. Never resend an uncertain/timed-out toggle.
    if let Ok(bus) = gio::bus_get_future(gio::BusType::Session).await {
        let locale: std::collections::HashMap<_, _> = ["LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES"]
            .into_iter().filter_map(|key| std::env::var(key).ok().map(|v| (key, v))).collect();
        let payload = serde_json::json!({"anchor": serde_json::from_str::<serde_json::Value>(&anchor).unwrap_or_default(),
            "side": null, "locale": locale, "prepare": prepare}).to_string();
        let parameters = ("open", vec![payload.to_variant()], std::collections::HashMap::<String, glib::Variant>::new()).to_variant();
        match bus.call_future(Some("org.adws.Sidebar"), "/org/adws/Sidebar", "org.gtk.Actions", "Activate",
            Some(&parameters), None, gio::DBusCallFlags::NO_AUTO_START, 1500).await {
            Ok(_) => return,
            Err(error) if sidebar_service_missing(&error) => {},
            Err(error) => { tracing::warn!(%error, "Sidebar request failed; not resending toggle"); return; }
        }
    }
    let mut command = std::process::Command::new("python3");
    command.arg(helper).arg("--anchor").arg(anchor);
    if prepare { command.arg("--prepare"); }
    match command.spawn() {
        Ok(mut child) => { std::thread::spawn(move || { let _ = child.wait(); }); },
        Err(error) => tracing::warn!(%error, "Cannot start sidebar"),
    }
}

#[test]
#[ignore = "requires isolated dbus-run-session and GTK display"]
fn sidebar_native_requests_reach_service_once_without_python() {
    gtk::init().unwrap();
    let app = gtk::Application::new(Some("org.adws.Sidebar"), gio::ApplicationFlags::FLAGS_NONE);
    let received = Rc::new(RefCell::new(Vec::new()));
    let values = received.clone();
    let action = gio::SimpleAction::new("open", Some(glib::VariantTy::STRING));
    action.connect_activate(move |_, parameter| {
        values.borrow_mut().push(serde_json::from_str::<serde_json::Value>(parameter.unwrap().str().unwrap()).unwrap());
    });
    app.add_action(&action);
    app.register(None::<&gio::Cancellable>).unwrap();
    assert!(!app.is_remote());
    let started = std::time::Instant::now();
    glib::MainContext::default().block_on(async {
        for prepare in [true, false, false] {
            request_sidebar("/nonexistent/adws-helper.py".into(), r#"{"edge":"bottom","x":42}"#.into(), prepare).await;
        }
    });
    assert_eq!(received.borrow().len(), 3);
    assert_eq!(received.borrow()[0]["prepare"], true);
    assert_eq!(received.borrow()[1]["prepare"], false);
    assert_eq!(received.borrow()[1]["anchor"]["x"], 42);
    println!("Three native sidebar requests: {:?}", started.elapsed());
}

pub(crate) fn sidebar(root: &gtk::Container, config: &Config) {
    let button = gtk::Button::new();
    button.set_relief(gtk::ReliefStyle::None);
    button.style_context().add_class("adws-quick-button");
    let image = gtk::Image::from_icon_name(Some("view-grid-symbolic"), gtk::IconSize::Button);
    image.set_pixel_size((config.thickness() as i32 - 14).clamp(16, 32));
    button.add(&image);
    button.set_tooltip_text(Some(crate::i18n::text("侧边栏", "Sidebar")));
    let helper = config.control_helper().to_owned();
    let edge = config.position().to_owned();
    let thickness = config.thickness();
    let warm_helper = helper.clone();
    let warm_edge = edge.clone();
    let last_prepare = Rc::new(Cell::new(None::<std::time::Instant>));
    button.connect_enter_notify_event(move |button, _| {
        if last_prepare.get().is_none_or(|t| t.elapsed() > Duration::from_secs(10)) {
            last_prepare.set(Some(std::time::Instant::now()));
            glib::spawn_future_local(request_sidebar(warm_helper.clone(), anchor(button, &warm_edge, thickness), true));
        }
        glib::Propagation::Proceed
    });
    button.connect_button_press_event(move |button, event| {
        if !matches!(event.button(), 1 | 3) { return glib::Propagation::Proceed; }
        if event.button() == 1 {
            glib::spawn_future_local(request_sidebar(helper.clone(), anchor(button, &edge, thickness), false));
            return glib::Propagation::Stop;
        }
        let mut command = std::process::Command::new("python3");
        let config = std::path::Path::new(&helper).with_file_name("adws-config.py");
        command.arg(config).arg("--tab").arg("sidebar");
        if let Ok(mut child) = command.spawn() {
            std::thread::spawn(move || { let _ = child.wait(); });
        }
        glib::Propagation::Stop
    });
    root.add(&button); button.show_all();
}

/// Hook the existing Waybar clock; preserve its format and right-click settings.
/// Generic events precede Waybar's own button handler, avoiding a double toggle.
pub(crate) fn connect_clock_control_center(widget: &gtk::Widget, helper: &str, edge: &str, thickness: u32) {
    if helper.is_empty() { return; }
    if widget.widget_name() == "clock" {
        let mut current = Some(widget.clone());
        while let Some(node) = current {
            if let Ok(target) = node.clone().downcast::<gtk::EventBox>() {
                let style = target.style_context();
                if style.has_class("adws-clock-center-hook") { break; }
                style.add_class("adws-clock-center-hook");
                let helper = helper.to_owned(); let edge = edge.to_owned();
                target.connect_event(move |button, event| {
                    if event.event_type() != gtk::gdk::EventType::ButtonPress { return glib::Propagation::Proceed; }
                    let Some(event) = event.downcast_ref::<gtk::gdk::EventButton>() else { return glib::Propagation::Proceed; };
                    if event.button() != 1 { return glib::Propagation::Proceed; }
                    match std::process::Command::new("python3").arg(&helper).arg("--anchor").arg(anchor(button, &edge, thickness)).spawn() {
                        Ok(mut child) => { std::thread::spawn(move || { let _ = child.wait(); }); }
                        Err(error) => tracing::warn!(%error, "Cannot open clock control center"),
                    }
                    glib::Propagation::Stop
                });
                break;
            }
            current = node.parent();
        }
    }
    if let Some(container) = widget.downcast_ref::<gtk::Container>() {
        for child in container.children() { connect_clock_control_center(&child, helper, edge, thickness); }
    }
}

fn anchor<W: IsA<gtk::Widget>>(button: &W, edge: &str, thickness: u32) -> String {
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
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn control_warning_preserves_icon_and_geometry_then_clears_on_recovery() {
        gtk::init().unwrap();
        for kind in ["sound", "brightness"] {
            let window = gtk::Window::new(gtk::WindowType::Toplevel);
            let button = gtk::Button::new();
            let (overlay, image, warning) = control_indicator(kind, 38);
            button.add(&overlay); window.add(&button); window.show_all();
            while gtk::events_pending() { gtk::main_iteration(); }
            let normal = if kind == "sound" { "audio-volume-medium-symbolic" } else { "display-brightness-symbolic" };
            apply_control_status(&button, &image, &warning, kind,
                &serde_json::json!({"icon":normal,"available":true,"text":"42%"}));
            assert!(!warning.is_visible());
            let before = overlay.preferred_size();
            apply_control_status(&button, &image, &warning, kind,
                &serde_json::json!({"icon":"dialog-warning-symbolic","available":false,"text":"—","error":"Connection terminated"}));
            button.show_all(); // outer layout refresh must not clear the alert
            while gtk::events_pending() { gtk::main_iteration(); }
            assert_eq!(image.icon_name().as_deref(), Some(normal));
            assert!(warning.is_visible());
            assert_eq!(warning.halign(), gtk::Align::End);
            assert_eq!(warning.valign(), gtk::Align::End);
            assert!(warning.pixel_size() < image.pixel_size());
            let after = overlay.preferred_size();
            assert_eq!((before.0.width, before.0.height, before.1.width, before.1.height),
                       (after.0.width, after.0.height, after.1.width, after.1.height));
            assert!(button.tooltip_text().unwrap().contains("Connection terminated"));
            if kind == "sound" {
                apply_control_status(&button, &image, &warning, kind,
                    &serde_json::json!({"state":"no-device","available":false,"text":"—"}));
                assert_eq!(image.icon_name().as_deref(), Some("audio-volume-muted-symbolic"));
                assert_eq!(warning.icon_name().as_deref(), Some("dialog-question-symbolic"));
                assert!(warning.is_visible());
                assert_eq!(warning.valign(), gtk::Align::Center);
                assert_eq!(image.margin_end(), warning.pixel_size().saturating_sub(5));
                assert_eq!(warning.pixel_size(), image.pixel_size() * 3 / 4);
                apply_control_status(&button, &image, &warning, kind,
                    &serde_json::json!({"available":false,"error":"Connection terminated"}));
                assert_eq!(warning.icon_name().as_deref(), Some("dialog-warning-symbolic"));
            }
            apply_control_status(&button, &image, &warning, kind,
                &serde_json::json!({"icon":normal,"available":true,"text":"42%"}));
            button.show_all();
            assert!(!warning.is_visible(), "layout refresh restored a stale warning");
            assert_eq!(image.margin_end(), 0);
            assert_eq!(warning.valign(), gtk::Align::End);
            assert!(!button.tooltip_text().unwrap().contains("Connection terminated"));
            unsafe { window.destroy(); }
        }
    }
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn explicit_refresh_wakes_status_worker_without_waiting_for_poll() {
        gtk::init().unwrap();
        let directory = std::env::temp_dir().join(format!("adws-control-refresh-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let helper = directory.join("helper.py");
        std::fs::write(&helper, r#"import json
from pathlib import Path
p=Path(__file__).with_suffix('.count')
n=int(p.read_text())+1 if p.exists() else 1
p.write_text(str(n))
print(json.dumps({'icon':'audio-volume-high-symbolic','available':True,'text':str(n)+'%'}))
"#).unwrap();
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        let root = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        window.add(&root);
        let config: Config = serde_json::from_value(serde_json::json!({
            "component":"sound", "control_helper":helper.to_str().unwrap()
        })).unwrap();
        let control = Controls::new(root.upcast_ref(), &config);
        window.show_all();
        let wait_for = |text: &str| {
            let until = std::time::Instant::now()+Duration::from_secs(1);
            while !control.button.tooltip_text().is_some_and(|value| value.ends_with(text)) {
                assert!(std::time::Instant::now()<until, "status did not refresh promptly");
                while gtk::events_pending() { gtk::main_iteration(); }
                std::thread::sleep(Duration::from_millis(2));
            }
        };
        wait_for("1%");
        control.refresh.try_send(()).unwrap();
        // Multiple requests during an outstanding update must remain bounded.
        assert!(control.refresh.try_send(()).is_err());
        wait_for("2%");
        drop(control);
        unsafe { window.destroy(); }
        std::fs::remove_dir_all(directory).unwrap();
    }
    use super::*;
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn sidebar_anchor_comes_from_its_widget_and_monitor() {
        gtk::init().unwrap();
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        let root = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        window.add(&root);
        window.set_default_size(1000, 100);
        let config: Config = serde_json::from_value(serde_json::json!({"component":"sidebar","position":"bottom","thickness":40})).unwrap();
        sidebar(root.upcast_ref(), &config);
        window.show_all();
        while gtk::events_pending() { gtk::main_iteration(); }
        let button = root.children()[0].clone().downcast::<gtk::Button>().unwrap();
        let value: serde_json::Value = serde_json::from_str(&anchor(&button,"bottom",40)).unwrap();
        assert_eq!(value["monitor"], 0);
        assert_eq!(value["edge"], "bottom");
        assert_eq!(value["inset"], 50);
        assert!(value["x"].as_i64().unwrap() < 500);
        assert!(button.is_visible());
        unsafe { window.destroy(); }
    }

    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn clock_hook_consumes_only_left_press_once() {
        gtk::init().unwrap();
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        let target = gtk::EventBox::new();
        let label = gtk::Label::new(Some("12:34")); label.set_widget_name("clock");
        target.add(&label); window.add(&target); window.show_all();
        while gtk::events_pending() { gtk::main_iteration(); }
        let folder = std::env::temp_dir().join(format!("adws-clock-hook-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        let helper = folder.join("helper.py"); let result = folder.join("calls.jsonl");
        std::fs::write(&helper, format!("import sys\nwith open({:?}, 'a') as f: f.write(sys.argv[2]+'\\n')\n", result.to_str().unwrap())).unwrap();
        for _ in 0..2 { connect_clock_control_center(window.upcast_ref(), helper.to_str().unwrap(), "right", 40); }
        let mut event = gtk::gdk::Event::new(gtk::gdk::EventType::ButtonPress).downcast::<gtk::gdk::EventButton>().unwrap();
        event.as_mut().button = 3;
        assert!(!target.emit_by_name::<bool>("event", &[&*event]));
        event.as_mut().button = 1;
        assert!(target.emit_by_name::<bool>("event", &[&*event]));
        for _ in 0..100 {
            if result.exists() { break; }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        let calls = std::fs::read_to_string(&result).unwrap();
        assert_eq!(calls.lines().count(), 1);
        let value: serde_json::Value = serde_json::from_str(calls.trim()).unwrap();
        assert_eq!(value["edge"], "right"); assert_eq!(value["inset"], 50);
        unsafe { window.destroy(); }
        std::fs::remove_dir_all(folder).unwrap();
    }

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

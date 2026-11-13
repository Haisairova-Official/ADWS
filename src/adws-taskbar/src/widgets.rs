//! GTK modules mounted alongside the native CFFI components of the bottom bar.
mod custom;
mod stream;
mod workspaces;

use gtk::{gdk, glib, pango, prelude::*};
use serde_json::{json, Value};
use std::{
    any::Any,
    cell::{Cell, RefCell},
    path::Path,
    rc::Rc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

enum Kind {
    Clock,
    Workspaces,
    Custom,
}
fn kind(name: &str) -> Option<Kind> {
    match name.split('#').next()? {
        "clock" => Some(Kind::Clock),
        "niri/workspaces" => Some(Kind::Workspaces),
        name if name
            .strip_prefix("custom/")
            .is_some_and(|id| !id.is_empty()) =>
        {
            Some(Kind::Custom)
        }
        _ => None,
    }
}
pub fn supports(name: &str) -> bool {
    kind(name).is_some()
}

pub fn mount(
    name: &str,
    config: &Value,
    root: &gtk::EventBox,
    output: &str,
    vertical: bool,
) -> Result<Box<dyn Any>, String> {
    match kind(name) {
        Some(Kind::Clock) => Ok(Box::new(clock(config, root))),
        Some(Kind::Workspaces) => Ok(Box::new(workspaces::mount(config, root, output, vertical)?)),
        Some(Kind::Custom) => custom::mount(config, root),
        _ => Err(format!("Unsupported taskbar module: {name}")),
    }
}

/// Called after all module guards have dropped, before the host process exits.
pub fn finish_shutdown() {
    custom::finish_shutdown();
}

fn field<'a>(config: &'a Value, key: &str, default: &'a str) -> &'a str {
    config.get(key).and_then(Value::as_str).unwrap_or(default)
}

fn label(config: &Value, root: &gtk::EventBox) -> gtk::Label {
    let label = gtk::Label::new(None);
    label.set_angle(config["rotate"].as_f64().unwrap_or(0.0));
    label.set_xalign(config["align"].as_f64().unwrap_or(0.5).clamp(0., 1.) as f32);
    label.set_justify(match field(config, "justify", "left") {
        "center" => gtk::Justification::Center,
        "right" => gtk::Justification::Right,
        _ => gtk::Justification::Left,
    });
    if let Some(n) = config["max-length"].as_i64().filter(|n| *n > 0) {
        label.set_max_width_chars(n.min(i32::MAX as i64) as i32);
        label.set_ellipsize(pango::EllipsizeMode::End);
    }
    root.add(&label);
    label.show();
    label
}

fn markup(label: &gtk::Label, value: &str) {
    if label.label().as_str() == value {
        return;
    }
    if value.contains(['<', '&']) && pango::parse_markup(value, '\0').is_ok() {
        label.set_markup(value);
    } else {
        label.set_text(value);
    }
}

fn tooltip(root: &gtk::EventBox, value: &str) {
    if value.is_empty() {
        root.set_tooltip_text(None);
    } else if pango::parse_markup(value, '\0').is_ok() {
        root.set_tooltip_markup(Some(value));
    } else {
        root.set_tooltip_text(Some(value));
    }
}

fn wheel(event: &gdk::EventScroll, remainder: &Cell<f64>) -> Option<&'static str> {
    use gdk::ScrollDirection::*;
    match event.direction() {
        Up => Some("on-scroll-up"),
        Down => Some("on-scroll-down"),
        Left => Some("on-scroll-left"),
        Right => Some("on-scroll-right"),
        Smooth => {
            let (dx, dy) = event.delta();
            let horizontal = dx.abs() > dy.abs();
            let delta = if horizontal { dx } else { dy };
            if !delta.is_finite() {
                return None;
            }
            let total = remainder.get() + delta;
            remainder.set(if total.abs() >= 1.0 {
                total.fract()
            } else {
                total
            });
            if total.abs() < 1.0 {
                None
            } else {
                Some(match (horizontal, total < 0.) {
                    (true, true) => "on-scroll-left",
                    (true, false) => "on-scroll-right",
                    (false, true) => "on-scroll-up",
                    (false, false) => "on-scroll-down",
                })
            }
        }
        _ => None,
    }
}

// The generated clock command identifies the control center. Give that command
// the monitor and coordinates of the actual clock, including duplicated clocks.
fn command_for(root: &gtk::EventBox, command: &str, anchored: bool) -> std::ffi::OsString {
    if anchored {
        if let Ok(argv) = glib::shell_parse_argv(command) {
            if argv.len() == 6
                && Path::new(&argv[1])
                    .file_name()
                    .is_some_and(|n| n == "adws_control_center.py")
                && argv[2] == "--edge"
                && argv[4] == "--inset"
            {
                if let Some(top) = root.toplevel() {
                    let display = root.display();
                    let monitor = top.window().and_then(|w| display.monitor_at_window(&w));
                    let index = (0..display.n_monitors())
                        .find(|i| display.monitor(*i) == monitor)
                        .unwrap_or(0);
                    let (x, y) = root.translate_coordinates(&top, 0, 0).unwrap_or_default();
                    let anchor = json!({"edge":argv[3].to_string_lossy(),"inset":argv[5].to_string_lossy().parse::<u32>().unwrap_or(46),
                        "x":x + root.allocated_width()/2,"y":y + root.allocated_height()/2,"monitor":index});
                    return [
                        glib::shell_quote(&argv[0]),
                        glib::shell_quote(&argv[1]),
                        "--anchor".into(),
                        glib::shell_quote(anchor.to_string()),
                    ]
                    .join(std::ffi::OsStr::new(" "));
                }
            }
        }
    }
    // GTK's async spawn reaps its child. User action commands retain shell semantics.
    [
        std::ffi::OsString::from("/bin/sh -c"),
        glib::shell_quote(command),
    ]
    .join(std::ffi::OsStr::new(" "))
}

fn actions(root: &gtk::EventBox, config: &Value, clock: bool) {
    let cfg = Rc::new(config.clone());
    root.add_events(
        gdk::EventMask::BUTTON_PRESS_MASK
            | gdk::EventMask::SCROLL_MASK
            | gdk::EventMask::SMOOTH_SCROLL_MASK,
    );
    let click = cfg.clone();
    root.connect_button_press_event(move |root, event| {
        if event.event_type() != gdk::EventType::ButtonPress {
            return glib::Propagation::Proceed;
        }
        let key = match event.button() {
            1 => "on-click",
            2 => "on-click-middle",
            3 => "on-click-right",
            _ => return glib::Propagation::Proceed,
        };
        launch_action(root, &click, key, clock && event.button() == 1)
    });
    let remainder = Cell::new(0.0);
    root.connect_scroll_event(move |root, event| {
        wheel(event, &remainder).map_or(glib::Propagation::Proceed, |key| {
            launch_action(root, &cfg, key, false)
        })
    });
}
fn launch_action(
    root: &gtk::EventBox,
    cfg: &Value,
    key: &str,
    anchored: bool,
) -> glib::Propagation {
    let command = field(cfg, key, "").trim();
    if command.is_empty() {
        return glib::Propagation::Proceed;
    }
    if let Err(err) = glib::spawn_command_line_async(command_for(root, command, anchored)) {
        eprintln!("Taskbar {key}: {err}");
    }
    glib::Propagation::Stop
}

fn clock_format(template: &str, date: &glib::DateTime) -> String {
    interpolate(template, |parameter| {
        parameter
            .strip_prefix("0:")
            .or_else(|| parameter.strip_prefix(':'))
            .and_then(|pat| date.format(pat).ok())
            .map(|s| s.to_string())
    })
}

/// Replace fields without interpreting braces inside plugin output or escaped braces in labels.
fn interpolate(template: &str, mut field: impl FnMut(&str) -> Option<String>) -> String {
    let mut out = String::with_capacity(template.len());
    let mut chars = template.char_indices().peekable();
    while let Some((_, ch)) = chars.next() {
        if matches!(ch, '{' | '}') && chars.peek().is_some_and(|(_, next)| *next == ch) {
            out.push(ch);
            chars.next();
            continue;
        }
        if ch == '{' {
            let start = chars.peek().map_or(template.len(), |(i, _)| *i);
            if let Some(end) = template[start..].find('}') {
                let key = &template[start..start + end];
                if let Some(value) = field(key) {
                    out.push_str(&value);
                } else {
                    out.push('{');
                    out.push_str(key);
                    out.push('}');
                }
                while chars.next_if(|(i, _)| *i <= start + end).is_some() {}
                continue;
            }
        }
        out.push(ch);
    }
    out
}

struct Clock {
    root: gtk::EventBox,
    label: gtk::Label,
    format: String,
    tip: Option<String>,
    seconds: u64,
    timer: RefCell<Option<glib::SourceId>>,
}
impl Clock {
    fn update(self: &Rc<Self>) {
        if let Ok(now) = glib::DateTime::now_local() {
            markup(&self.label, &clock_format(&self.format, &now));
            if let Some(tip) = &self.tip {
                tooltip(&self.root, &clock_format(tip, &now));
            }
        }
        let interval = self.seconds * 1000;
        let ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;
        let weak = Rc::downgrade(self);
        *self.timer.borrow_mut() = Some(glib::timeout_add_local_once(
            Duration::from_millis(interval - ms % interval),
            move || {
                if let Some(clock) = weak.upgrade() {
                    clock.timer.borrow_mut().take();
                    clock.update();
                }
            },
        ));
    }
}
impl Drop for Clock {
    fn drop(&mut self) {
        if let Some(id) = self.timer.get_mut().take() {
            id.remove();
        }
    }
}
fn clock(config: &Value, root: &gtk::EventBox) -> Rc<Clock> {
    let clock = Rc::new(Clock {
        root: root.clone(),
        label: label(config, root),
        format: field(config, "format", "{:%H:%M}").into(),
        tip: (config["tooltip"].as_bool() != Some(false))
            .then(|| field(config, "tooltip-format", "{:%F %A}").to_string()),
        seconds: config["interval"].as_u64().unwrap_or(60).clamp(1, 86400),
        timer: RefCell::new(None),
    });
    // The embedded window-list plugin also looks for a Waybar clock to hook.
    root.style_context().add_class("adws-clock-center-hook");
    actions(root, config, true);
    clock.update();
    clock
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    pub(crate) fn repeated_stream_mounts_release_workers_and_signal_sources() {
        gtk::init().unwrap();
        let mine = || {
            std::fs::read_dir("/proc/self/task")
                .unwrap()
                .flatten()
                .filter(|e| {
                    std::fs::read_to_string(e.path().join("comm"))
                        .is_ok_and(|n| n.trim() == "adws-custom")
                })
                .count()
        };
        let baseline = mine();
        for _ in 0..16 {
            let root = gtk::EventBox::new();
            let cfg = json!({"exec":"while :; do printf '1\\n2\\n3\\n4\\n'; done"});
            let guard = mount("custom/busy", &cfg, &root, "fixture", false).unwrap();
            std::thread::sleep(Duration::from_millis(6));
            glib::MainContext::default().iteration(false);
            drop(guard);
            unsafe {
                root.destroy();
            }
        }
        finish_shutdown();
        assert_eq!(mine(), baseline, "stream workers survived GTK unmount");
    }
    pub(crate) fn live_widget_stream_and_launch() {
        gtk::init().unwrap();
        let folder = std::env::temp_dir().join(format!("adws-widget-test-{}", std::process::id()));
        std::fs::create_dir(&folder).unwrap();
        let action = folder.join("clicked");
        let scroll = folder.join("scrolled");
        let root = gtk::EventBox::new();
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        let title = format!("ADWS widget fixture {}", std::process::id());
        window.set_title(&title);
        window.set_default_size(240, 80);
        window.add(&root);
        let cfg = json!({"exec":"printf '%s\\n' '{\"text\":\"first\",\"class\":\"before\"}'; sleep .1; printf '%s\\n' '{\"text\":\"<b>second</b>\",\"class\":[\"after\"],\"tooltip\":\"Details\"}'; exec sleep 30", "return-type":"json", "on-click":format!("printf clicked > {}",glib::shell_quote(&action).to_str().unwrap()), "on-scroll-up":format!("printf scrolled > {}",glib::shell_quote(&scroll).to_str().unwrap())});
        let guard = mount("custom/proof", &cfg, &root, "fixture", false).unwrap();
        window.show_all();
        let rendered_label = root.child().unwrap().downcast::<gtk::Label>().unwrap();
        let deadline = std::time::Instant::now() + Duration::from_secs(3);
        while !rendered_label.style_context().has_class("after")
            && std::time::Instant::now() < deadline
        {
            while gtk::events_pending() {
                gtk::main_iteration();
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!(root.is_visible() && rendered_label.style_context().has_class("after"));
        assert!(!rendered_label.style_context().has_class("before"));
        let label = root.child().unwrap().downcast::<gtk::Label>().unwrap();
        assert_eq!(label.text().as_str(), "second");
        assert_eq!(root.tooltip_text().unwrap().as_str(), "Details");
        let status = std::process::Command::new("xdotool")
            .args([
                "search",
                "--name",
                &title,
                "mousemove",
                "--window",
                "%@",
                "80",
                "35",
                "click",
                "1",
                "click",
                "4",
            ])
            .status()
            .unwrap();
        assert!(status.success());
        let deadline = std::time::Instant::now() + Duration::from_secs(3);
        while (!action.exists() || !scroll.exists()) && std::time::Instant::now() < deadline {
            while gtk::events_pending() {
                gtk::main_iteration();
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(std::fs::read_to_string(action).unwrap(), "clicked");
        assert_eq!(std::fs::read_to_string(scroll).unwrap(), "scrolled");
        drop(guard);
        finish_shutdown();
        unsafe {
            window.destroy();
        }
        std::fs::remove_dir_all(folder).unwrap();
    }
    #[test]
    fn clock_matches_generated_formatter() {
        let date = glib::DateTime::from_unix_utc(50).unwrap();
        assert_eq!(
            clock_format("<b>{0:%H:%M:%S}</b>\n{:%F}", &date),
            "<b>00:00:50</b>\n1970-01-01"
        );
    }
    #[test]
    fn interpolation_does_not_interpret_plugin_data() {
        assert_eq!(
            interpolate("{{{text}}}", |k| (k == "text").then(|| "{text}".into())),
            "{{text}}"
        );
    }
}

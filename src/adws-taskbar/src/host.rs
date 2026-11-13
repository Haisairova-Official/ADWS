use crate::{cffi, widgets};
use glib::translate::{from_glib_full, ToGlibPtr};
use gtk::{gdk, glib, prelude::*};
use serde_json::Value;
use std::{
    any::Any,
    cell::{Cell, RefCell},
    collections::HashMap,
    fs::File,
    io::{BufRead, BufReader, Read, Write},
    os::unix::net::UnixStream,
    path::{Path, PathBuf},
    rc::Rc,
    time::Duration,
};

#[link(name = "gtk-layer-shell")]
extern "C" {
    fn gtk_layer_is_supported() -> i32;
    fn gtk_layer_init_for_window(window: *mut gtk::ffi::GtkWindow);
    fn gtk_layer_set_monitor(window: *mut gtk::ffi::GtkWindow, monitor: *mut gdk::ffi::GdkMonitor);
    fn gtk_layer_set_layer(window: *mut gtk::ffi::GtkWindow, layer: i32);
    fn gtk_layer_set_anchor(window: *mut gtk::ffi::GtkWindow, edge: i32, enabled: i32);
    fn gtk_layer_set_margin(window: *mut gtk::ffi::GtkWindow, edge: i32, margin: i32);
    fn gtk_layer_auto_exclusive_zone_enable(window: *mut gtk::ffi::GtkWindow);
    fn gtk_layer_set_exclusive_zone(window: *mut gtk::ffi::GtkWindow, zone: i32);
    fn gtk_layer_set_keyboard_mode(window: *mut gtk::ffi::GtkWindow, mode: i32);
    fn gtk_layer_set_namespace(window: *mut gtk::ffi::GtkWindow, name: *const std::ffi::c_char);
}

const MAX_CONFIG: usize = 2 * 1024 * 1024;
const EDGES: [&str; 4] = ["left", "right", "top", "bottom"];
const SLOTS: [&str; 3] = ["modules-left", "modules-center", "modules-right"];

pub struct Config {
    raw: Value,
    edge: usize,
    layer: i32,
    thickness: i32,
    margins: [i32; 4],
    spacing: i32,
    exclusive: bool,
    fixed_center: bool,
    slots: [Vec<String>; 3],
    outputs: Vec<String>,
}

impl Config {
    pub fn read(path: &Path) -> Result<Self, String> {
        let mut text = Vec::new();
        File::open(path)
            .and_then(|f| f.take(MAX_CONFIG as u64 + 1).read_to_end(&mut text))
            .map_err(|e| format!("Cannot read {}: {e}", path.display()))?;
        if text.len() > MAX_CONFIG {
            return Err("Taskbar configuration exceeds 2 MiB".into());
        }
        let value = serde_json::from_slice(&text)
            .map_err(|e| format!("Invalid expanded taskbar JSON: {e}"))?;
        Self::parse(value)
    }
    fn parse(value: Value) -> Result<Self, String> {
        let raw = match value {
            Value::Object(_) => value,
            Value::Array(mut bars) if bars.len() == 1 && bars[0].is_object() => bars.remove(0),
            _ => return Err("Expected one expanded taskbar configuration object".into()),
        };
        if raw.get("include").is_some() {
            return Err("Expand taskbar includes before starting the native host".into());
        }
        let parse_enum = |key, default: &str, values: &[&str]| {
            let value = match raw.get(key) {
                Some(Value::String(s)) => s,
                None => default,
                _ => return Err(format!("Invalid {key}")),
            };
            values
                .iter()
                .position(|v| *v == value)
                .ok_or_else(|| format!("Unsupported {key}: {value}"))
        };
        let integer = |key, default, low, high| match raw.get(key) {
            None => Ok(default),
            Some(v) => v
                .as_i64()
                .filter(|n| (low..=high).contains(n))
                .map(|n| n as i32)
                .ok_or_else(|| format!("Invalid {key}")),
        };
        let edge = parse_enum("position", "bottom", &EDGES)?;
        let layer = parse_enum("layer", "top", &["background", "bottom", "top", "overlay"])? as i32;
        let thickness = integer(if edge < 2 { "width" } else { "height" }, 36, 0, 4096)?;
        let spacing = integer("spacing", 0, 0, 1024)?;
        let mut margins = [0; 4];
        for (i, margin) in ["margin-left", "margin-right", "margin-top", "margin-bottom"]
            .iter()
            .enumerate()
        {
            margins[i] = integer(margin, 0, -4096, 4096)?;
        }
        let mut slots = [Vec::new(), Vec::new(), Vec::new()];
        for (i, slot) in SLOTS.iter().enumerate() {
            if let Some(items) = raw.get(*slot) {
                let items = items
                    .as_array()
                    .ok_or_else(|| format!("{slot} must be a module list"))?;
                for item in items {
                    let name = item
                        .as_str()
                        .filter(|v| !v.is_empty())
                        .ok_or_else(|| format!("Invalid module in {slot}"))?;
                    if raw
                        .get(name)
                        .is_some_and(|definition| !definition.is_object())
                    {
                        return Err(format!("Invalid module definition: {name}"));
                    }
                    slots[i].push(name.to_owned());
                }
            }
        }
        let outputs = match raw.get("output") {
            None => vec![],
            Some(Value::String(s)) => vec![s.clone()],
            Some(Value::Array(items)) => items
                .iter()
                .map(|v| {
                    v.as_str()
                        .map(str::to_owned)
                        .ok_or("Invalid output selector")
                })
                .collect::<Result<_, _>>()?,
            _ => return Err("Invalid output selector".into()),
        };
        let exclusive = raw
            .get("exclusive")
            .map(|v| v.as_bool().ok_or("Invalid exclusive setting"))
            .transpose()?
            .unwrap_or(true);
        let fixed_center = raw
            .get("fixed-center")
            .map(|v| v.as_bool().ok_or("Invalid fixed-center setting"))
            .transpose()?
            .unwrap_or(true);
        Ok(Self {
            raw,
            edge,
            layer,
            thickness,
            margins,
            spacing,
            exclusive,
            fixed_center,
            slots,
            outputs,
        })
    }
    pub fn validate_modules(&self) -> Result<(), String> {
        let mut failures = Vec::new();
        for name in self.slots.iter().flatten() {
            if name.starts_with("cffi/") {
                match self.raw[name]["module_path"].as_str() {
                    Some(path) if Path::new(path).is_file() => {}
                    Some(path) => failures.push(format!("{name}: missing module library {path}")),
                    None => failures.push(format!("{name}: missing module_path")),
                }
            } else if !widgets::supports(name) {
                failures.push(format!("Unsupported taskbar module: {name}"));
            }
        }
        if failures.is_empty() {
            Ok(())
        } else {
            Err(failures.join("\n"))
        }
    }

    fn matches(&self, name: &str, description: &str) -> bool {
        let matches =
            |s: &str| s == "*" || s == name || (!description.is_empty() && s == description);
        if self
            .outputs
            .iter()
            .filter_map(|s| s.strip_prefix('!'))
            .any(matches)
        {
            return false;
        }
        let positive: Vec<_> = self
            .outputs
            .iter()
            .filter(|s| !s.starts_with('!'))
            .collect();
        positive.is_empty() || positive.iter().any(|s| matches(s))
    }
}

// Niri's logical coordinates disambiguate identical monitors. GTK3's legacy
// plug name can instead contain a model name on some Wayland backends.
fn niri_outputs() -> HashMap<String, Value> {
    let read = || -> Option<_> {
        let mut stream = UnixStream::connect(std::env::var_os("NIRI_SOCKET")?).ok()?;
        let timeout = Some(Duration::from_millis(200));
        stream.set_read_timeout(timeout).ok()?;
        stream.set_write_timeout(timeout).ok()?;
        stream.write_all(b"\"Outputs\"\n").ok()?;
        let mut line = Vec::new();
        BufReader::new(stream)
            .take(MAX_CONFIG as u64)
            .read_until(b'\n', &mut line)
            .ok()?;
        let response: Value = serde_json::from_slice(&line).ok()?;
        serde_json::from_value(response.get("Ok")?.get("Outputs")?.clone()).ok()
    };
    read().unwrap_or_default()
}

fn monitor_identity(
    display: &gdk::Display,
    index: i32,
    monitor: &gdk::Monitor,
    outputs: &HashMap<String, Value>,
) -> (String, String) {
    let geometry = monitor.geometry();
    let matched: Vec<_> = outputs
        .iter()
        .filter(|(_, out)| {
            let g = &out["logical"];
            g["x"].as_i64() == Some(i64::from(geometry.x()))
                && g["y"].as_i64() == Some(i64::from(geometry.y()))
                && g["width"].as_i64() == Some(i64::from(geometry.width()))
                && g["height"].as_i64() == Some(i64::from(geometry.height()))
        })
        .collect();
    if let [(name, out)] = matched.as_slice() {
        let description = ["make", "model", "serial"]
            .map(|key| out[key].as_str().unwrap_or("Unknown"))
            .join(" ");
        return ((*name).clone(), description);
    }
    let screen = display.default_screen();
    let plug: Option<glib::GString> = unsafe {
        from_glib_full(gdk::ffi::gdk_screen_get_monitor_plug_name(
            screen.to_glib_none().0,
            index,
        ))
    };
    (
        plug.map(|s| s.to_string()).unwrap_or_default(),
        String::new(),
    )
}

fn css_id(name: &str) -> String {
    let base = name.split('#').next().unwrap_or(name);
    if let Some(suffix) = base.strip_prefix("custom/") {
        format!("custom-{suffix}")
    } else {
        base.rsplit('/').next().unwrap_or(base).to_string()
    }
}

fn style_module(widget: &gtk::Widget, name: &str) {
    widget.set_widget_name(&css_id(name));
    let style = widget.style_context();
    style.add_class("module");
    if let Some((_, instance)) = name.split_once('#') {
        style.add_class(instance);
    }
}

type Guard = Box<dyn Any>;
struct Bar {
    monitor: gdk::Monitor,
    window: gtk::Window,
    modules: Vec<Guard>,
    exclusive: bool,
}
impl Drop for Bar {
    fn drop(&mut self) {
        while let Some(guard) = self.modules.pop() {
            drop(guard);
        }
        // Every external module has disconnected its GTK callbacks by now.
        unsafe {
            self.window.destroy();
        }
    }
}
impl Bar {
    fn mount(
        config: &Config,
        monitor: &gdk::Monitor,
        output: &str,
        preview: bool,
        hidden: bool,
    ) -> Result<Self, String> {
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        let mut bar = Self {
            monitor: monitor.clone(),
            window,
            modules: vec![],
            exclusive: config.exclusive && !preview,
        };
        let window = &bar.window;
        window.set_widget_name("waybar");
        window.style_context().add_class(EDGES[config.edge]);
        window.set_title("ADWS taskbar");
        window.set_decorated(false);
        if let Some(visual) = gtk::prelude::WidgetExt::screen(window).and_then(|s| s.rgba_visual())
        {
            window.set_visual(Some(&visual));
        }
        let vertical = config.edge < 2;
        let orientation = if vertical {
            gtk::Orientation::Vertical
        } else {
            gtk::Orientation::Horizontal
        };
        let thickness = config.thickness.max(1);
        if vertical {
            window.set_size_request(thickness, -1);
            window.set_default_size(thickness, 1);
        } else {
            window.set_size_request(-1, thickness);
            window.set_default_size(1, thickness);
        }
        unsafe {
            let ptr = window.to_glib_none().0;
            gtk_layer_init_for_window(ptr);
            gtk_layer_set_namespace(
                ptr,
                if preview {
                    c"adws-taskbar-preview"
                } else {
                    c"adws-taskbar"
                }
                .as_ptr(),
            );
            gtk_layer_set_monitor(ptr, monitor.to_glib_none().0);
            gtk_layer_set_layer(ptr, config.layer);
            gtk_layer_set_keyboard_mode(ptr, 0);
            for (i, margin) in config.margins.iter().enumerate() {
                let anchor = i == config.edge || (i < 2) != vertical;
                gtk_layer_set_anchor(ptr, i as i32, i32::from(anchor));
                gtk_layer_set_margin(ptr, i as i32, *margin);
            }
        }
        let row = gtk::Box::new(orientation, 0);
        window.add(&row);
        let sections = SLOTS.map(|slot| {
            let section = gtk::Box::new(orientation, config.spacing);
            section.style_context().add_class(slot);
            section
        });
        row.pack_start(&sections[0], false, false, 0);
        if config.fixed_center {
            row.set_center_widget(Some(&sections[1]));
        } else {
            row.pack_start(&sections[1], true, false, 0);
        }
        row.pack_end(&sections[2], false, false, 0);
        for (slot, section) in config.slots.iter().zip(sections.iter()) {
            for name in slot {
                let root = gtk::EventBox::new();
                // In Waybar, ALabel modules style their label itself. GTK3
                // event boxes do not honor CSS minimum sizes on their child.
                let base = name.split('#').next().unwrap_or(name);
                let label_module = base == "clock" || base.starts_with("custom/");
                root.set_visible_window(!label_module);
                if !label_module {
                    style_module(root.upcast_ref(), name);
                }
                section.pack_start(&root, false, false, 0);
                let mut definition = config
                    .raw
                    .get(name)
                    .cloned()
                    .unwrap_or_else(|| serde_json::json!({}));
                if matches!(
                    name.as_str(),
                    "cffi/system-brightness" | "cffi/system-sound" | "cffi/system-sidebar"
                ) && !output.is_empty()
                {
                    definition["control_output"] = Value::String(output.to_string());
                }
                let guard = if name.starts_with("cffi/") {
                    cffi::mount(name, &definition, &root)
                } else {
                    widgets::mount(name, &definition, &root, output, vertical)
                };
                bar.modules
                    .push(guard.map_err(|error| format!("{output}: {name}: {error}"))?);
                if label_module {
                    if let Some(child) = root.child() {
                        style_module(&child, name);
                    }
                }
            }
        }
        if hidden {
            row.show_all();
        } else {
            bar.visible(true);
        }
        Ok(bar)
    }
    fn visible(&self, visible: bool) {
        let ptr = self.window.to_glib_none().0;
        if visible {
            self.window.style_context().remove_class("mode-invisible");
            unsafe {
                if self.exclusive {
                    gtk_layer_auto_exclusive_zone_enable(ptr);
                } else {
                    gtk_layer_set_exclusive_zone(ptr, 0);
                }
            }
            self.window.show_all();
        } else {
            self.window.style_context().add_class("mode-invisible");
            unsafe {
                gtk_layer_set_exclusive_zone(ptr, 0);
            }
            self.window.hide();
        }
    }
}

struct Host {
    config: RefCell<Rc<Config>>,
    display: gdk::Display,
    bars: RefCell<Vec<Bar>>,
    hidden: Cell<bool>,
    visibility_marker: Option<PathBuf>,
    preview: bool,
}
impl Host {
    fn refresh(&self) -> Result<(), String> {
        let monitors: Vec<_> = (0..self.display.n_monitors())
            .filter_map(|i| self.display.monitor(i).map(|m| (i, m)))
            .collect();
        self.bars
            .borrow_mut()
            .retain(|bar| monitors.iter().any(|(_, m)| *m == bar.monitor));
        if monitors
            .iter()
            .all(|(_, m)| self.bars.borrow().iter().any(|bar| bar.monitor == *m))
        {
            return Ok(());
        }
        let config = self.config.borrow().clone();
        let outputs = niri_outputs();
        for (index, monitor) in monitors {
            if self.bars.borrow().iter().any(|bar| bar.monitor == monitor) {
                continue;
            }
            let (name, description) = monitor_identity(&self.display, index, &monitor, &outputs);
            if config.matches(&name, &description) {
                let bar = Bar::mount(&config, &monitor, &name, self.preview, self.hidden.get())?;
                self.bars.borrow_mut().push(bar);
            }
        }
        Ok(())
    }
    fn unmount(&self) {
        self.bars.borrow_mut().clear();
        cffi::finish_shutdown();
        widgets::finish_shutdown();
    }

    fn reload(&self, path: &Path, style: &Rc<crate::style::Style>) -> Result<(), String> {
        let next = Config::read(path)?;
        next.validate_modules()?;
        // Stop old instances before reusing the same plugin/watchdog identities.
        // In particular only one tray watcher can own the session bus name.
        self.unmount();
        let previous = self.config.replace(Rc::new(next));
        if let Err(error) = self.refresh().and_then(|()| style.reload()) {
            self.unmount();
            self.config.replace(previous);
            self.refresh().map_err(|restore| {
                format!("{error}; could not restore previous layout: {restore}")
            })?;
            return Err(error);
        }
        Ok(())
    }
    fn toggle(&self) {
        // The managed toggle publishes the desired state before it signals us.
        // Re-reading it also handles rapid clicks that coalesce into one signal.
        let hidden = self
            .visibility_marker
            .as_ref()
            .map_or_else(|| !self.hidden.get(), |marker| marker.is_file());
        self.hidden.set(hidden);
        for bar in &*self.bars.borrow() {
            bar.visible(!self.hidden.get());
        }
    }
}

pub fn run(config: Config, config_path: &Path, style: &Path) -> Result<(), String> {
    gtk::init().map_err(|e| format!("Cannot initialize GTK: {e}"))?;
    if unsafe { gtk_layer_is_supported() } == 0 {
        return Err("A Wayland compositor with layer-shell support is required".into());
    }
    let display = gdk::Display::default().ok_or("No GDK display")?;
    let stylesheet = crate::style::Style::load(
        style,
        &display.default_screen(),
        config
            .raw
            .get("reload_style_on_change")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    )?;
    let preview =
        std::env::var_os("ADWS_TASKBAR_PREVIEW").as_deref() == Some(std::ffi::OsStr::new("1"));
    let managed =
        std::env::var_os("ADWS_TASKBAR_MANAGED").as_deref() == Some(std::ffi::OsStr::new("1"));
    let visibility_marker = (managed && !preview).then(|| {
        std::env::var_os("XDG_STATE_HOME")
            .filter(|dir| !dir.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| glib::home_dir().join(".local/state"))
            .join("taskbar-hidden")
    });
    let host = Rc::new(Host {
        config: RefCell::new(Rc::new(config)),
        display: display.clone(),
        bars: RefCell::new(vec![]),
        hidden: Cell::new(false),
        visibility_marker,
        preview,
    });
    let error = Rc::new(RefCell::new(None));
    let schedule = {
        let host = Rc::downgrade(&host);
        let error = error.clone();
        let pending = Rc::new(Cell::new(false));
        move || {
            if pending.replace(true) {
                return;
            }
            let host = host.clone();
            let error = error.clone();
            let pending = pending.clone();
            glib::idle_add_local_once(move || {
                pending.set(false);
                if let Some(host) = host.upgrade() {
                    if let Err(e) = host.refresh() {
                        error.replace(Some(e));
                        gtk::main_quit();
                    }
                }
            });
        }
    };
    let added = display.connect_monitor_added({
        let schedule = schedule.clone();
        move |_, _| schedule()
    });
    let removed = display.connect_monitor_removed(move |_, _| schedule());
    let toggle = glib::unix_signal_add_local(libc::SIGUSR1, {
        let host = host.clone();
        move || {
            host.toggle();
            glib::ControlFlow::Continue
        }
    });
    let reload = glib::unix_signal_add_local(libc::SIGUSR2, {
        let host = host.clone();
        let path = config_path.to_owned();
        move || {
            if let Err(error) = host.reload(&path, &stylesheet) {
                eprintln!("adws-taskbar: cannot apply configuration: {error}");
            }
            glib::ControlFlow::Continue
        }
    });
    let stopping = Rc::new(Cell::new(false));
    let stop = [libc::SIGTERM, libc::SIGINT, libc::SIGHUP].map(|signal| {
        let stopping = stopping.clone();
        glib::unix_signal_add_local(signal, move || {
            stopping.set(true);
            if gtk::main_level() != 0 {
                gtk::main_quit();
            }
            glib::ControlFlow::Continue
        })
    });
    // Install signal handlers before mounting plugins: interruption during a
    // multi-output startup must still run their deinitializers.
    // A toggle can commit its marker while we are registering SIGUSR1.
    // From this point on the handler will pick up any subsequent change.
    if let Some(marker) = &host.visibility_marker {
        host.hidden.set(marker.is_file());
    }
    let initial = host.refresh();
    if initial.is_ok() && !stopping.get() {
        gtk::main();
    }
    for source in stop {
        source.remove();
    }
    reload.remove();
    toggle.remove();
    display.disconnect(added);
    display.disconnect(removed);
    host.bars.borrow_mut().clear();
    initial?;
    match error.take() {
        Some(e) => Err(e),
        None => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn parses_all_edges_and_preserves_repeated_module_order() {
        for edge in EDGES {
            let cfg=Config::parse(json!({"position":edge,"width":48,"height":36,"modules-right":["clock#one","clock#two"]})).unwrap();
            assert_eq!(
                cfg.thickness,
                if matches!(edge, "left" | "right") {
                    48
                } else {
                    36
                }
            );
            assert_eq!(cfg.slots[2], ["clock#one", "clock#two"]);
        }
    }
    #[test]
    fn input_is_an_expanded_single_bar() {
        assert!(Config::parse(json!([{}, {}])).is_err());
        assert!(Config::parse(json!({"include":"other.json"})).is_err());
        assert!(Config::parse(json!({"modules-left":[null]})).is_err());
        assert!(Config::parse(json!({"position":false})).is_err());
    }
    #[test]
    fn check_only_validates_active_modules_and_never_loads_a_library() {
        let exe = std::env::current_exe().unwrap();
        let config = Config::parse(json!({
            "modules-left": ["clock#one", "niri/workspaces", "custom/test", "cffi/probe"],
            "cffi/probe": {"module_path": exe},
            "cffi/disabled": {"module_path": "/missing/disabled.so"}
        }))
        .unwrap();
        assert!(config.validate_modules().is_ok());
        let broken = Config::parse(json!({
            "modules-right": ["cffi/probe", "cffi/no-path", "unknown#bad"],
            "cffi/probe": {"module_path": "/missing-library.so"}
        }))
        .unwrap();
        let errors = broken.validate_modules().unwrap_err();
        for bad in [
            "cffi/probe",
            "/missing-library.so",
            "cffi/no-path",
            "unknown#bad",
        ] {
            assert!(errors.contains(bad), "{errors}");
        }
    }

    #[test]
    fn output_selectors_support_mixed_lists_and_exclusions() {
        for (selectors, found) in [
            (json!(["*", "!DP-2"]), true),
            (json!(["DP-2"]), false),
            (json!("Dell U2723QE 123"), true),
            (json!(["!DP-1"]), false),
        ] {
            let cfg = Config::parse(json!({"output":selectors})).unwrap();
            assert_eq!(cfg.matches("DP-1", "Dell U2723QE 123"), found);
        }
    }
}

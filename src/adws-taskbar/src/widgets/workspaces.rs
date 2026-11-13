use super::{
    field, interpolate, markup,
    stream::{self, Worker},
    wheel,
};
use gtk::{gdk, glib, prelude::*};
use serde_json::{json, Value};
use std::{
    cell::{Cell, RefCell},
    collections::HashMap,
    io::{self, Write},
    os::unix::net::UnixStream,
    rc::Rc,
    time::Duration,
};

#[derive(Clone, PartialEq)]
struct Workspace {
    id: u64,
    index: u64,
    name: String,
    output: String,
    active: bool,
    focused: bool,
    urgent: bool,
    empty: bool,
}
impl Workspace {
    fn read(value: &Value) -> Option<Self> {
        Some(Self {
            id: value["id"].as_u64()?,
            index: value["idx"].as_u64()?,
            name: field(value, "name", "").into(),
            output: field(value, "output", "").into(),
            active: value["is_active"] == true,
            focused: value["is_focused"] == true,
            urgent: value["is_urgent"] == true,
            empty: value["active_window_id"].is_null(),
        })
    }
    fn title(&self) -> String {
        if self.name.is_empty() {
            self.index.to_string()
        } else {
            self.name.clone()
        }
    }
}
fn observe(state: &mut Vec<Workspace>, event: &Value) -> bool {
    if let Some(rows) = event["WorkspacesChanged"]["workspaces"].as_array() {
        *state = rows.iter().filter_map(Workspace::read).collect();
        return true;
    }
    if let Some(v) = event.get("WorkspaceActivated") {
        let Some(id) = v["id"].as_u64() else {
            return false;
        };
        let Some(output) = state.iter().find(|w| w.id == id).map(|w| w.output.clone()) else {
            return false;
        };
        for w in state {
            if w.output == output {
                w.active = w.id == id;
            }
            if v["focused"] == true {
                w.focused = w.id == id;
            }
        }
        return true;
    }
    if let Some(v) = event.get("WorkspaceUrgencyChanged") {
        if let Some(w) = state.iter_mut().find(|w| Some(w.id) == v["id"].as_u64()) {
            w.urgent = v["urgent"] == true;
            return true;
        }
    }
    if let Some(v) = event.get("WorkspaceActiveWindowChanged") {
        if let Some(w) = state
            .iter_mut()
            .find(|w| Some(w.id) == v["workspace_id"].as_u64())
        {
            let empty = v["active_window_id"].is_null();
            if empty != w.empty {
                w.empty = empty;
                return true;
            }
        }
    }
    false
}
fn socket() -> io::Result<UnixStream> {
    let path = std::env::var_os("NIRI_SOCKET")
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "NIRI_SOCKET is unavailable"))?;
    let socket = UnixStream::connect(path)?;
    socket.set_write_timeout(Some(Duration::from_millis(250)))?;
    Ok(socket)
}
fn focus(id: u64) {
    // Niri's FocusWorkspace reference supports stable ids across output reordering.
    std::thread::spawn(move || {
        let result = socket().and_then(|mut s| {
            writeln!(
                s,
                "{}",
                json!({"Action":{"FocusWorkspace":{"reference":{"Id":id}}}})
            )?;
            s.set_read_timeout(Some(Duration::from_secs(1)))?;
            use std::io::{BufRead, BufReader, Read};
            let mut line = String::new();
            BufReader::new(s).take(16384).read_line(&mut line)?;
            if serde_json::from_str::<Value>(&line)
                .ok()
                .and_then(|v| v.get("Ok").cloned())
                .is_none()
            {
                return Err(io::Error::other(
                    "Niri declined the workspace focus request",
                ));
            }
            Ok(())
        });
        if let Err(err) = result {
            eprintln!("Taskbar workspace focus: {err}");
        }
    });
}
fn shown(mut rows: Vec<Workspace>, cfg: &Value, output: &str) -> Vec<Workspace> {
    rows.retain(|w| {
        (cfg["all-outputs"] == true || output.is_empty() || w.output == output)
            && (cfg["current-only"] != true || w.focused || w.active)
            && (cfg["hide-empty"] != true || !w.empty)
            && match field(cfg, "display-condition", "show-all") {
                "keep-named" => !w.empty || !w.name.is_empty(),
                "only-populated" => !w.empty,
                _ => true,
            }
    });
    if cfg["sort-by-id"] == true || cfg["sort-by-number"] == true {
        rows.sort_by_key(|w| w.id);
    } else if cfg["sort-by-name"] == true {
        if rows.iter().all(|w| w.title().parse::<u64>().is_ok()) {
            rows.sort_by_key(|w| w.title().parse::<u64>().unwrap());
        } else {
            rows.sort_by_key(Workspace::title);
        }
    } else {
        rows.sort_by(|a, b| (&a.output, a.index).cmp(&(&b.output, b.index)));
    }
    rows
}
fn display(row: &Workspace, cfg: &Value, total: usize) -> String {
    let title = row.title();
    let mut keys = vec![title.as_str()];
    if row.urgent {
        keys.push("urgent");
    }
    if row.focused {
        keys.push("focused");
    }
    if row.active {
        keys.push("active");
    }
    if row.empty {
        keys.push("empty");
    }
    keys.push("default");
    let icon = keys
        .iter()
        .find_map(|k| cfg["format-icons"].get(k).and_then(Value::as_str))
        .unwrap_or("");
    interpolate(field(cfg, "format", "{value}"), |key| {
        Some(match key {
            "value" => title.clone(),
            "name" => row.name.clone(),
            "index" => row.index.to_string(),
            "output" => row.output.clone(),
            "icon" => icon.into(),
            "total" => total.to_string(),
            _ => return None,
        })
    })
}
pub(super) fn mount(
    config: &Value,
    root: &gtk::EventBox,
    output: &str,
    vertical: bool,
) -> Result<Worker, String> {
    let content = gtk::Box::new(
        if vertical {
            gtk::Orientation::Vertical
        } else {
            gtk::Orientation::Horizontal
        },
        0,
    );
    root.add(&content);
    content.show();
    let snapshot = Rc::new(RefCell::new(Vec::<Workspace>::new()));
    if config["disable-scroll"] != true {
        root.add_events(gdk::EventMask::SCROLL_MASK | gdk::EventMask::SMOOTH_SCROLL_MASK);
        let remainder = Cell::new(0.0);
        let rows = snapshot.clone();
        let output = output.to_owned();
        root.connect_scroll_event(move |_, event| {
            let Some(action) = wheel(event, &remainder) else {
                return glib::Propagation::Proceed;
            };
            let rows = rows.borrow();
            if let Some(at) = rows
                .iter()
                .position(|w| w.active && w.output == output)
                .or_else(|| rows.iter().position(|w| w.focused))
            {
                let i = if matches!(action, "on-scroll-up" | "on-scroll-left") {
                    at.saturating_sub(1)
                } else {
                    (at + 1).min(rows.len() - 1)
                };
                if i != at {
                    focus(rows[i].id);
                }
            }
            glib::Propagation::Stop
        });
    }
    let cfg = config.clone();
    let output = output.to_owned();
    let mut buttons = HashMap::<u64, (gtk::Button, gtk::Label)>::new();
    Worker::start(
        "adws-workspaces",
        move |rows: Vec<Workspace>| {
            let total = rows.len();
            let rows = shown(rows, &cfg, &output);
            buttons.retain(|id, (button, _)| {
                let keep = rows.iter().any(|w| w.id == *id);
                if !keep {
                    content.remove(button);
                }
                keep
            });
            for (at, row) in rows.iter().enumerate() {
                let (button, label) = buttons.entry(row.id).or_insert_with(|| {
                    let button = gtk::Button::new();
                    button.set_relief(gtk::ReliefStyle::None);
                    button.style_context().add_class("niri-workspace");
                    let label = gtk::Label::new(None);
                    button.add(&label);
                    content.pack_start(&button, false, false, 0);
                    if cfg["disable-click"] != true {
                        let id = row.id;
                        button.connect_clicked(move |_| focus(id));
                    }
                    button.show_all();
                    (button, label)
                });
                let text = display(row, &cfg, total);
                if cfg["disable-markup"] == true {
                    label.set_text(&text);
                } else {
                    markup(label, &text);
                }
                button.set_widget_name(&format!("niri-workspace-{}", row.title()));
                content.reorder_child(button, at as i32);
                let ctx = button.style_context();
                for (name, enabled) in [
                    ("active", row.active),
                    ("focused", row.focused),
                    ("urgent", row.urgent),
                    ("empty", row.empty),
                    ("current_output", row.output == output),
                ] {
                    if enabled {
                        ctx.add_class(name);
                    } else {
                        ctx.remove_class(name);
                    }
                }
            }
            *snapshot.borrow_mut() = rows;
        },
        move |stop, updates| loop {
            let connected = socket().and_then(|mut socket| {
                socket.write_all(b"\"EventStream\"\n")?;
                let mut state = Vec::new();
                stream::lines(&mut socket, &stop, |line| {
                    if let Ok(event) = serde_json::from_slice::<Value>(line) {
                        if observe(&mut state, &event) {
                            updates.publish(state.clone());
                        }
                    }
                })
            });
            if matches!(connected, Ok(false)) {
                break;
            }
            updates.publish(Vec::new());
            if !stream::delay(&stop, Duration::from_secs(2)) {
                break;
            }
        },
    )
    .map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn focus_event_keeps_other_outputs_active() {
        let mut rows = vec![];
        assert!(observe(
            &mut rows,
            &json!({"WorkspacesChanged":{"workspaces":[
          {"id":80,"idx":1,"output":"A","is_active":true,"is_focused":true},
          {"id":44,"idx":1,"output":"B","is_active":true}, {"id":45,"idx":2,"output":"B","name":"code"}]}})
        ));
        assert!(observe(
            &mut rows,
            &json!({"WorkspaceActivated":{"id":45,"focused":true}})
        ));
        assert!(rows[0].active && !rows[0].focused && !rows[1].active && rows[2].focused);
        let filtered = shown(rows, &json!({}), "B");
        assert_eq!(filtered.len(), 2);
        assert_eq!(display(&filtered[1], &json!({}), 3), "code");
    }
}

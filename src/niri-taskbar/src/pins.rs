//! Persistent application pins, independent of running window IDs.
use serde::Deserialize;
use std::{path::PathBuf, time::Duration};

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
pub struct Pin {
    pub app_id: String,
    pub desktop_id: String,
    pub name: String,
}
impl Pin {
    pub fn matches(&self, app: Option<&str>) -> bool {
        app.is_some_and(|app| {
            identity(app) == identity(&self.app_id) || identity(app) == identity(&self.desktop_id)
        })
    }
}
pub fn identity(app: &str) -> String {
    app.trim_end_matches(".desktop").to_lowercase()
}
pub fn path() -> PathBuf {
    std::env::var_os("XDG_CONFIG_HOME")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config")
        })
        .join("mnws/taskbar-pins.json")
}
pub fn load() -> Result<Vec<Pin>, String> {
    let data = match std::fs::read(path()) {
        Ok(data) => data,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(vec![]),
        Err(e) => return Err(e.to_string()),
    };
    #[derive(Deserialize)]
    struct File {
        version: u32,
        apps: Vec<Pin>,
    }
    let file: File = serde_json::from_slice(&data).map_err(|e| e.to_string())?;
    if file.version != 1
        || file
            .apps
            .iter()
            .any(|p| p.app_id.is_empty() || p.desktop_id.is_empty())
    {
        return Err("invalid taskbar pin file".into());
    }
    let mut result: Vec<Pin> = vec![];
    for pin in file.apps {
        if !result
            .iter()
            .any(|p| p.matches(Some(&pin.app_id)) || p.matches(Some(&pin.desktop_id)))
        {
            result.push(pin);
        }
    }
    Ok(result)
}
pub fn is_pinned(app: &str) -> bool {
    load()
        .unwrap_or_default()
        .iter()
        .any(|p| p.matches(Some(app)))
}
pub async fn watch(tx: async_channel::Sender<crate::state::Event>) {
    let mut previous = load().unwrap_or_default();
    if tx
        .send(crate::state::Event::PinsChanged(previous.clone()))
        .await
        .is_err()
    {
        return;
    }
    loop {
        waybar_cffi::gtk::glib::timeout_future(Duration::from_millis(500)).await;
        let Ok(pins) = load() else {
            continue;
        }; // Preserve the last valid file during replacement/errors.
        if pins != previous {
            previous = pins.clone();
            if tx
                .send(crate::state::Event::PinsChanged(pins))
                .await
                .is_err()
            {
                break;
            }
        }
    }
}
/// Resolve exactly the focused-card selector without changing a live card's state.
pub fn focus_color(
    widget: &impl waybar_cffi::gtk::prelude::IsA<waybar_cffi::gtk::Widget>,
) -> waybar_cffi::gtk::gdk::RGBA {
    use waybar_cffi::gtk::{self as gtk, prelude::*};
    let context = gtk::StyleContext::new();
    let parent = widget.parent().unwrap_or_else(|| widget.clone().upcast());
    let path = parent.path();
    let index = path.append_type(gtk::Button::static_type());
    path.iter_set_object_name(index, Some("button"));
    path.iter_add_class(index, "focused");
    context.set_path(&path);
    context.set_parent(Some(&parent.style_context()));
    let css = gtk::CssProvider::new();
    let _ = css.load_from_data(include_bytes!("style.css"));
    context.add_provider(&css, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION - 1);
    context
        .style_property_for_state("background-color", gtk::StateFlags::NORMAL)
        .get()
        .unwrap_or_else(|_| gtk::gdk::RGBA::new(0.5, 0.5, 0.5, 1.))
}
pub fn separator(vertical: bool) -> waybar_cffi::gtk::DrawingArea {
    use waybar_cffi::gtk::{self as gtk, prelude::*};
    let line = gtk::DrawingArea::new();
    line.style_context().add_class("mnws-pin-separator");
    if vertical {
        line.set_size_request(-1, 9);
    } else {
        line.set_size_request(9, -1);
    }
    line.connect_draw(move |widget, cr| {
        let color = focus_color(widget);
        cr.set_source_rgba(color.red(), color.green(), color.blue(), color.alpha());
        let w = widget.allocated_width() as f64;
        let h = widget.allocated_height() as f64;
        if vertical {
            cr.rectangle(w * 0.2, (h - 2.) / 2., w * 0.6, 2.);
        } else {
            cr.rectangle((w - 2.) / 2., h * 0.2, 2., h * 0.6);
        }
        let _ = cr.fill();
        gtk::glib::Propagation::Stop
    });
    line
}

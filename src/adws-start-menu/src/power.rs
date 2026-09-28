//! Session actions are discovered and executed asynchronously. Tests inject the
//! dispatcher: no automated test ever calls a real power/logout operation.
use crate::{add_class, config_home, icon_button, Text};
use gtk::{gio, glib, prelude::*};
use std::{
    cell::{Cell, RefCell},
    collections::HashMap,
    ffi::OsString,
    os::unix::fs::{FileTypeExt, MetadataExt},
    rc::Rc,
};

const SERVICE: &str = "org.freedesktop.login1";
const MANAGER_PATH: &str = "/org/freedesktop/login1";
const MANAGER: &str = "org.freedesktop.login1.Manager";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Action {
    Lock,
    Logout,
    Suspend,
    Hibernate,
    Reboot,
    PowerOff,
}
impl Action {
    const ALL: [Self; 6] = [
        Self::Lock,
        Self::Logout,
        Self::Suspend,
        Self::Hibernate,
        Self::Reboot,
        Self::PowerOff,
    ];
    fn caption(self) -> &'static str {
        match self {
            Self::Lock => "锁屏",
            Self::Logout => "注销",
            Self::Suspend => "挂起",
            Self::Hibernate => "休眠",
            Self::Reboot => "重启",
            Self::PowerOff => "关机",
        }
    }
    fn icon(self) -> &'static str {
        match self {
            Self::Lock => "system-lock-screen-symbolic",
            Self::Logout => "system-log-out-symbolic",
            Self::Suspend => "media-playback-pause-symbolic",
            Self::Hibernate => "weather-clear-night-symbolic",
            Self::Reboot => "system-reboot-symbolic",
            Self::PowerOff => "system-shutdown-symbolic",
        }
    }
    fn destructive(self) -> bool {
        matches!(self, Self::Logout | Self::Reboot | Self::PowerOff)
    }
    fn confirmation(self) -> &'static str {
        match self {
            Self::Logout => "确定要注销当前会话吗？请先保存工作，未保存的内容可能丢失。",
            Self::Reboot => "确定要重启计算机吗？请先保存工作，未保存的内容可能丢失。",
            Self::PowerOff => "确定要关闭计算机吗？请先保存工作，未保存的内容可能丢失。",
            _ => "",
        }
    }
    fn method(self) -> &'static str {
        match self {
            Self::Suspend => "Suspend",
            Self::Hibernate => "Hibernate",
            Self::Reboot => "Reboot",
            Self::PowerOff => "PowerOff",
            _ => "",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
enum Route {
    Command(Vec<OsString>),
    Session(String),
    Power(&'static str),
}
#[derive(Default)]
struct Backend {
    bus: Option<gio::DBusConnection>,
    routes: HashMap<Action, Route>,
}
fn allowed(reply: &str) -> bool {
    matches!(reply, "yes" | "challenge")
}
async fn query(
    bus: &gio::DBusConnection,
    method: &str,
    args: Option<&glib::Variant>,
) -> Result<glib::Variant, glib::Error> {
    bus.call_future(
        Some(SERVICE),
        MANAGER_PATH,
        MANAGER,
        method,
        args,
        None,
        gio::DBusCallFlags::NONE,
        1500,
    )
    .await
}
fn local_routes() -> HashMap<Action, Route> {
    let mut routes = HashMap::new();
    // A logind Lock signal alone is not a lock screen. Only offer a concrete
    // available locker, preserving the user's Niri-specific hyprlock config.
    for program in ["hyprlock", "gtklock", "swaylock", "waylock"] {
        if let Some(binary) = glib::find_program_in_path(program) {
            let mut args = vec![binary.into_os_string()];
            let config = config_home().join("niri/hyprlock.conf");
            if program == "hyprlock"
                && std::env::var_os("NIRI_SOCKET").is_some()
                && config.is_file()
            {
                args.extend(["-c".into(), config.into_os_string()]);
            }
            routes.insert(Action::Lock, Route::Command(args));
            break;
        }
    }
    let niri_socket = std::env::var_os("NIRI_SOCKET")
        .is_some_and(|path| std::fs::metadata(path).is_ok_and(|m| m.file_type().is_socket()));
    if niri_socket {
        if let Some(binary) = glib::find_program_in_path("niri") {
            // ADWS supplies its own confirmation. Never terminate all sessions
            // for a user or use a process-name kill as a logout fallback.
            routes.insert(
                Action::Logout,
                Route::Command(vec![
                    binary.into_os_string(),
                    "msg".into(),
                    "action".into(),
                    "quit".into(),
                    "--skip-confirmation".into(),
                ]),
            );
        }
    }
    routes
}
async fn discover() -> Backend {
    let mut backend = Backend {
        routes: local_routes(),
        bus: None,
    };
    let Ok(bus) = gio::bus_get_future(gio::BusType::System).await else {
        return backend;
    };
    for action in [
        Action::Suspend,
        Action::Hibernate,
        Action::Reboot,
        Action::PowerOff,
    ] {
        if let Ok(reply) = query(&bus, &format!("Can{}", action.method()), None).await {
            if reply
                .get::<(String,)>()
                .is_some_and(|(answer,)| allowed(&answer))
            {
                backend.routes.insert(action, Route::Power(action.method()));
            }
        }
    }
    if let std::collections::hash_map::Entry::Vacant(slot) = backend.routes.entry(Action::Logout) {
        let mut result = query(
            &bus,
            "GetSessionByPID",
            Some(&(std::process::id(),).to_variant()),
        )
        .await;
        if result.is_err() {
            if let Ok(id) = std::env::var("XDG_SESSION_ID") {
                result = query(&bus, "GetSession", Some(&(id,).to_variant())).await;
            }
        }
        if let Ok(reply) = result {
            if let Some((path,)) = reply.get::<(glib::variant::ObjectPath,)>() {
                let props = bus
                    .call_future(
                        Some(SERVICE),
                        &path,
                        "org.freedesktop.DBus.Properties",
                        "GetAll",
                        Some(&("org.freedesktop.login1.Session",).to_variant()),
                        None,
                        gio::DBusCallFlags::NONE,
                        1500,
                    )
                    .await;
                if let Ok(props) = props {
                    if let Some((props,)) = props.get::<(HashMap<String, glib::Variant>,)>() {
                        let graphical = props
                            .get("Type")
                            .and_then(|v| v.str())
                            .is_some_and(|s| matches!(s, "wayland" | "x11"));
                        let local =
                            props.get("Remote").and_then(|v| v.get::<bool>()) == Some(false);
                        let user = props
                            .get("User")
                            .and_then(|v| v.get::<(u32, glib::variant::ObjectPath)>());
                        let ours = user.is_some_and(|(uid, _)| {
                            std::fs::metadata("/proc/self").is_ok_and(|m| m.uid() == uid)
                        });
                        let active =
                            props.get("Active").and_then(|v| v.get::<bool>()) == Some(true);
                        if graphical && local && ours && active {
                            slot.insert(Route::Session(path.to_string()));
                        }
                    }
                }
            }
        }
    }
    backend.bus = Some(bus);
    backend
}
async fn execute(backend: Rc<Backend>, action: Action) -> Result<(), String> {
    let route = backend
        .routes
        .get(&action)
        .ok_or_else(|| "Operation is no longer available".to_string())?;
    match route {
        Route::Command(args) => {
            let args: Vec<_> = args.iter().map(|s| s.as_os_str()).collect();
            let child = gio::Subprocess::newv(
                &args,
                gio::SubprocessFlags::STDOUT_SILENCE | gio::SubprocessFlags::STDERR_SILENCE,
            )
            .map_err(|e| e.to_string())?;
            child.wait_check_future().await.map_err(|e| e.to_string())
        }
        Route::Power(method) => {
            let bus = backend.bus.as_ref().ok_or("Login manager is unavailable")?;
            // Interactive polkit and the standard logind path retain inhibitors.
            bus.call_future(
                Some(SERVICE),
                MANAGER_PATH,
                MANAGER,
                method,
                Some(&(true,).to_variant()),
                None,
                gio::DBusCallFlags::NONE,
                120_000,
            )
            .await
            .map(|_| ())
            .map_err(|e| e.to_string())
        }
        Route::Session(path) => {
            let bus = backend.bus.as_ref().ok_or("Login manager is unavailable")?;
            bus.call_future(
                Some(SERVICE),
                path,
                "org.freedesktop.login1.Session",
                "Terminate",
                None,
                None,
                gio::DBusCallFlags::NONE,
                15_000,
            )
            .await
            .map(|_| ())
            .map_err(|e| e.to_string())
        }
    }
}

type Dispatch = Rc<dyn Fn(Action)>;
pub(crate) struct PowerMenu {
    pages: gtk::Stack,
    list: gtk::Box,
    note: gtk::Label,
    title: gtk::Label,
    confirm: gtk::Button,
    cancel: gtk::Button,
    entry: gtk::Button,
    pending: Cell<Option<Action>>,
    busy: Cell<bool>,
    generation: Cell<u64>,
    text: Text,
    dispatch: RefCell<Option<Dispatch>>,
}
impl PowerMenu {
    pub(crate) fn new(pages: &gtk::Stack, footer: &gtk::Box, text: &Text) -> Rc<Self> {
        let page = gtk::Box::new(gtk::Orientation::Vertical, 12);
        page.set_border_width(20);
        add_class(&page, "power-page");
        let header = gtk::Box::new(gtk::Orientation::Horizontal, 12);
        let back = icon_button(&text.get("返回"), "go-previous-symbolic");
        header.pack_start(&back, false, false, 0);
        let caption = gtk::Label::new(Some(&text.get("电源与会话")));
        add_class(&caption, "power-title");
        header.pack_start(&caption, true, true, 0);
        page.pack_start(&header, false, false, 0);
        let list = gtk::Box::new(gtk::Orientation::Vertical, 4);
        let scroll = crate::scrolled(&list);
        page.pack_start(&scroll, true, true, 0);
        let note = gtk::Label::new(None);
        note.set_line_wrap(true);
        note.set_xalign(0.);
        page.pack_start(&note, false, false, 0);
        pages.add_named(&page, "power");
        let question = gtk::Box::new(gtk::Orientation::Vertical, 20);
        question.set_border_width(24);
        question.set_valign(gtk::Align::Center);
        add_class(&question, "power-page");
        let symbol =
            gtk::Image::from_icon_name(Some("system-shutdown-symbolic"), gtk::IconSize::Dialog);
        question.pack_start(&symbol, false, false, 0);
        let title = gtk::Label::new(None);
        title.set_line_wrap(true);
        title.set_max_width_chars(32);
        title.set_justify(gtk::Justification::Center);
        add_class(&title, "power-title");
        question.pack_start(&title, false, false, 0);
        let buttons = gtk::Box::new(gtk::Orientation::Horizontal, 12);
        buttons.set_halign(gtk::Align::Center);
        let cancel = gtk::Button::with_label(&text.get("取消"));
        let confirm = gtk::Button::with_label(&text.get("确定"));
        add_class(&confirm, "power-destructive");
        buttons.pack_start(&cancel, false, false, 0);
        buttons.pack_start(&confirm, false, false, 0);
        question.pack_start(&buttons, false, false, 0);
        pages.add_named(&question, "power-confirm");
        let entry = icon_button(&text.get("电源与会话"), "system-shutdown-symbolic");
        add_class(&entry, "power-entry");
        footer.pack_end(&entry, false, false, 0);
        let this = Rc::new(Self {
            pages: pages.clone(),
            list,
            note,
            title,
            confirm,
            cancel,
            entry,
            pending: Cell::new(None),
            busy: Cell::new(false),
            generation: Cell::new(0),
            text: text.clone(),
            dispatch: RefCell::new(None),
        });
        let weak = Rc::downgrade(&this);
        back.connect_clicked(move |_| {
            if let Some(this) = weak.upgrade() {
                this.back();
            }
        });
        let weak = Rc::downgrade(&this);
        this.cancel.connect_clicked(move |_| {
            if let Some(this) = weak.upgrade() {
                this.back();
            }
        });
        let weak = Rc::downgrade(&this);
        this.confirm.connect_clicked(move |_| {
            if let Some(this) = weak.upgrade() {
                if let Some(action) = this.pending.take() {
                    this.run(action);
                }
            }
        });
        this
    }
    pub(crate) fn busy(&self) -> bool {
        self.busy.get()
    }
    pub(crate) fn active(&self) -> bool {
        self.pages
            .visible_child_name()
            .is_some_and(|name| name != "launcher")
    }
    pub(crate) fn back(&self) {
        if self.busy.get() {
            return;
        }
        self.pending.set(None);
        if self.pages.visible_child_name().as_deref() == Some("power-confirm") {
            self.pages.set_visible_child_name("power");
            self.list.child_focus(gtk::DirectionType::TabForward);
        } else {
            self.pages.set_visible_child_name("launcher");
            self.entry.grab_focus();
        }
    }
    fn choose(&self, action: Action) {
        if self.busy.get() {
            return;
        }
        if action.destructive() {
            self.pending.set(Some(action));
            self.title.set_text(&self.text.get(action.confirmation()));
            self.confirm.set_label(&self.text.get(action.caption()));
            self.pages.set_visible_child_name("power-confirm");
            self.cancel.grab_focus();
        } else {
            self.run(action);
        }
    }
    fn run(&self, action: Action) {
        if self.busy.replace(true) {
            return;
        }
        if let Some(dispatch) = self.dispatch.borrow().as_ref() {
            dispatch(action);
        } else {
            self.busy.set(false);
        }
    }
    fn populate(self: &Rc<Self>, actions: impl IntoIterator<Item = Action>) {
        for child in self.list.children() {
            self.list.remove(&child);
        }
        for action in actions {
            let button = icon_button(&self.text.get(action.caption()), action.icon());
            add_class(&button, "power-action");
            let weak = Rc::downgrade(self);
            button.connect_clicked(move |_| {
                if let Some(this) = weak.upgrade() {
                    this.choose(action);
                }
            });
            self.list.pack_start(&button, false, false, 0);
        }
        self.note
            .set_text(&self.text.get(if self.list.children().is_empty() {
                "当前没有可用的电源操作。"
            } else {
                "部分操作可能需要系统授权。"
            }));
        self.list.show_all();
    }
    pub(crate) fn connect(
        self: &Rc<Self>,
        application: &gtk::Application,
        window: &gtk::ApplicationWindow,
    ) {
        let app = application.clone();
        let win = window.clone();
        let weak = Rc::downgrade(self);
        self.entry.connect_clicked(move |_| {
            if let Some(this) = weak.upgrade() {
                this.pages.set_visible_child_name("power");
                this.refresh(&app, &win);
            }
        });
        self.refresh(application, window);
    }
    fn refresh(self: &Rc<Self>, application: &gtk::Application, window: &gtk::ApplicationWindow) {
        if self.busy.get() {
            return;
        }
        let generation = self.generation.get() + 1;
        self.generation.set(generation);
        self.note.set_text(&self.text.get("正在检查可用操作…"));
        let weak = Rc::downgrade(self);
        let app = application.clone();
        let win = window.clone();
        glib::MainContext::default().spawn_local(async move {
            let backend = Rc::new(discover().await);
            let Some(this) = weak.upgrade() else {
                return;
            };
            if this.generation.get() != generation || this.busy.get() {
                return;
            }
            let available: Vec<_> = Action::ALL
                .into_iter()
                .filter(|action| backend.routes.contains_key(action))
                .collect();
            let weak = Rc::downgrade(&this);
            this.dispatch.replace(Some(Rc::new(move |action| {
                let weak = weak.clone();
                let app = app.clone();
                let win = win.clone();
                let backend = backend.clone();
                // Release the overlay's keyboard grab so polkit/locker can appear.
                win.hide();
                glib::MainContext::default().spawn_local(async move {
                    match execute(backend, action).await {
                        Ok(()) => app.quit(),
                        Err(error) => {
                            if let Some(this) = weak.upgrade() {
                                this.busy.set(false);
                                this.pending.set(None);
                                this.pages.set_visible_child_name("power");
                                this.note.set_text(&format!(
                                    "{} {error}",
                                    this.text.get("操作未完成：")
                                ));
                                win.show_all();
                                this.list.child_focus(gtk::DirectionType::TabForward);
                            }
                        }
                    }
                });
            })));
            this.populate(available);
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn capability_answers_do_not_turn_denials_into_actions() {
        assert!(allowed("yes"));
        assert!(allowed("challenge"));
        for reply in ["no", "na", "", "unknown"] {
            assert!(!allowed(reply));
        }
        for action in Action::ALL {
            assert_eq!(
                action.destructive(),
                matches!(action, Action::Logout | Action::Reboot | Action::PowerOff)
            );
        }
        assert_eq!(Action::PowerOff.method(), "PowerOff");
        assert_eq!(Action::Reboot.method(), "Reboot");
    }
    #[test]
    #[ignore = "requires an isolated GTK display; dispatcher is a recording fake"]
    fn confirmation_cancel_and_duplicate_activation_never_dispatch_unexpectedly() {
        gtk::init().unwrap();
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        window.set_default_size(500, 550);
        let pages = gtk::Stack::new();
        let launcher = gtk::Box::new(gtk::Orientation::Vertical, 0);
        let footer = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        launcher.add(&footer);
        pages.add_named(&launcher, "launcher");
        window.add(&pages);
        let text = Text {
            zh: true,
            table: serde_json::Value::Null,
        };
        let ui = PowerMenu::new(&pages, &footer, &text);
        let recorded = Rc::new(RefCell::new(Vec::new()));
        let calls = recorded.clone();
        ui.dispatch
            .replace(Some(Rc::new(move |action| calls.borrow_mut().push(action))));
        ui.populate(Action::ALL);
        window.show_all();
        for action in [Action::Logout, Action::Reboot, Action::PowerOff] {
            pages.set_visible_child_name("power");
            ui.choose(action);
            assert_eq!(pages.visible_child_name().as_deref(), Some("power-confirm"));
            assert!(recorded.borrow().is_empty());
            assert_eq!(ui.confirm.label().as_deref(), Some(action.caption()));
            ui.cancel.emit_clicked();
            assert_eq!(pages.visible_child_name().as_deref(), Some("power"));
            assert_eq!(ui.pending.get(), None);
            assert!(recorded.borrow().is_empty());
            ui.choose(action);
            ui.back();
            assert!(recorded.borrow().is_empty());
        }
        for action in Action::ALL {
            ui.busy.set(false);
            ui.choose(action);
            if action.destructive() {
                ui.confirm.emit_clicked();
                ui.confirm.emit_clicked();
            } else {
                ui.choose(action);
            }
        }
        assert_eq!(*recorded.borrow(), Action::ALL);
        ui.busy.set(false);
        ui.populate([Action::Logout]);
        assert_eq!(ui.list.children().len(), 1);
        pages.set_visible_child_name("power");
        ui.back();
        assert!(!ui.active());
        unsafe {
            window.destroy();
        }
    }
}

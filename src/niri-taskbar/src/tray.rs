//! Owned SNI widgets: three visible icons and an inward overflow popover.
//! No reparenting Waybar's internal tray widgets, blocking IPC or polling.
use crate::{config::Config, tasks::Tasks};
use glib::{translate::*, variant::ToVariant};
use std::{
    cell::{Cell, RefCell},
    collections::HashMap,
    ffi::{CString, c_void},
    rc::Rc,
    sync::{Arc, Mutex, OnceLock},
};
use waybar_cffi::gtk::{self, gio, glib, prelude::*};
const WATCHER: &str = "org.kde.StatusNotifierWatcher";
const WP: &str = "/StatusNotifierWatcher";
const ITEM: &str = "org.kde.StatusNotifierItem";
const XML: &str = r#"<node><interface name="org.kde.StatusNotifierWatcher"><method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method><method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method><property name="RegisteredStatusNotifierItems" type="as" access="read"/><property name="IsStatusNotifierHostRegistered" type="b" access="read"/><property name="ProtocolVersion" type="i" access="read"/><signal name="StatusNotifierItemRegistered"><arg type="s"/></signal><signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal><signal name="StatusNotifierHostRegistered"/></interface></node>"#;

pub(crate) struct Tray {
    bar: gtk::Box,
    grid: gtk::Grid,
    arrow: gtk::MenuButton,
    popup: gtk::Popover,
    focus_handler: RefCell<Option<(glib::WeakRef<gtk::Window>, glib::SignalHandlerId)>>,
    keyboard_focus: RefCell<Option<crate::button::PopupKeyboardFocus>>,
    _arrow_tip: Rc<TrayTip>,
    edge: String,
    items: RefCell<HashMap<String, Rc<Item>>>,
    order: RefCell<Vec<String>>,
    size: i32,
    tasks: RefCell<Tasks>,
    bus: RefCell<Option<gio::DBusConnection>>,
    registrations: RefCell<Vec<gio::RegistrationId>>,
    owners: RefCell<Vec<gio::OwnerId>>,
    signals: RefCell<Vec<gio::SignalSubscriptionId>>,
    watcher_items: Arc<Mutex<Vec<String>>>,
}
struct Item {
    button: gtk::Button,
    _tip: Rc<TrayTip>,
    image: gtk::Image,
    proxy: gio::DBusProxy,
    active: Cell<bool>,
    menu: RefCell<Option<gtk::Menu>>,
    refresh: RefCell<Option<glib::JoinHandle<()>>>,
    refresh_dirty: Cell<bool>,
    handlers: RefCell<Vec<glib::SignalHandlerId>>,
    size: i32,
    icon_theme: RefCell<Option<(String, gtk::IconTheme)>>,
    icon_properties: RefCell<HashMap<String,glib::Variant>>,
    icon_signature: RefCell<Option<(Vec<Option<glib::Variant>>,i32,gtk::gdk::RGBA)>>,
}
// Native GTK tooltips can use the layer origin for overflow-popup icons.
// Anchor each description to its actual button, including nested popups.
struct TrayTip {
    popup: gtk::Popover,
    label: gtk::Label,
    button: glib::WeakRef<gtk::Button>,
    pending: RefCell<Option<glib::SourceId>>,
}
impl TrayTip {
    fn new(button: &gtk::Button, edge: &str) -> Rc<Self> {
        button.set_has_tooltip(false);
        let popup=gtk::Popover::new(Some(button));popup.set_modal(false);
        popup.set_constrain_to(gtk::PopoverConstraint::None);
        popup.set_position(match edge {
            "top"=>gtk::PositionType::Bottom,"left"=>gtk::PositionType::Right,
            "right"=>gtk::PositionType::Left,_=>gtk::PositionType::Top,
        });
        popup.style_context().add_class("adws-tray-overflow");
        let label=gtk::Label::new(None);label.set_max_width_chars(48);label.set_line_wrap(true);
        label.set_margin_top(8);label.set_margin_bottom(8);label.set_margin_start(12);label.set_margin_end(12);popup.add(&label);
        let tip=Rc::new(Self {popup,label,button:button.downgrade(),pending:RefCell::new(None)});
        let weak=Rc::downgrade(&tip);
        button.connect_enter_notify_event(move |_,_| {
            if let Some(tip)=weak.upgrade() {
                tip.hide();let weak=Rc::downgrade(&tip);
                *tip.pending.borrow_mut()=Some(glib::timeout_add_local_once(std::time::Duration::from_millis(350),move || {
                    if let Some(tip)=weak.upgrade() {
                        tip.pending.borrow_mut().take();
                        if let Some(button)=tip.button.upgrade() {
                            if button.is_mapped() {
                                if let Some(text)=button.tooltip_text().filter(|s|!s.is_empty()) {
                                    tip.label.set_text(&text);tip.popup.show_all();tip.popup.popup();
                                }
                            }
                        }
                    }
                }));
            }
            glib::Propagation::Proceed
        });
        let weak=Rc::downgrade(&tip);
        button.connect_leave_notify_event(move |_,_| {if let Some(tip)=weak.upgrade(){tip.hide();} glib::Propagation::Proceed});
        let weak=Rc::downgrade(&tip);
        button.connect_button_press_event(move |_,_| {if let Some(tip)=weak.upgrade(){tip.hide();} glib::Propagation::Proceed});
        let weak=Rc::downgrade(&tip);
        button.connect_unmap(move |_| {if let Some(tip)=weak.upgrade(){tip.hide();}});
        tip
    }
    fn hide(&self) {
        if let Some(id)=self.pending.borrow_mut().take(){id.remove();}
        self.popup.popdown();
    }
}
impl Drop for TrayTip {
    fn drop(&mut self) {
        if let Some(id)=self.pending.get_mut().take(){id.remove();}
        self.popup.popdown();unsafe{self.popup.destroy();}
    }
}
impl Drop for Item {
    fn drop(&mut self) {
        if let Some(t) = self.refresh.get_mut().take() {
            t.abort();
        }
        for id in self.handlers.get_mut().drain(..) {
            self.proxy.disconnect(id);
        }
        if let Some(m) = self.menu.get_mut().take() {
            m.popdown();
            unsafe {
                m.destroy();
            }
        }
    }
}
impl Drop for Tray {
    fn drop(&mut self) {
        self.disconnect_focus_handler();
        for t in &self.tasks.get_mut().0 {
            t.abort();
        }
        if let Some(bus) = self.bus.get_mut().take() {
            for id in self.signals.get_mut().drain(..) {
                bus.signal_unsubscribe(id);
            }
            for id in self.registrations.get_mut().drain(..) {
                let _ = bus.unregister_object(id);
            }
        }
        for id in self.owners.get_mut().drain(..) {
            gio::bus_unown_name(id);
        }
        self.popup.popdown();
        unsafe {
            self.popup.destroy();
        }
    }
}
impl Tray {
    pub fn new(root: &gtk::Container, config: &Config) -> Rc<Self> {
        crate::menu_style::watch_palette();
        let bar = gtk::Box::new(
            if config.vertical() {
                gtk::Orientation::Vertical
            } else {
                gtk::Orientation::Horizontal
            },
            4,
        );
        bar.style_context().add_class("adws-tray");
        root.add(&bar);
        let arrow = gtk::MenuButton::new();
        arrow.set_relief(gtk::ReliefStyle::None);
        arrow.set_image(Some(&gtk::Image::from_icon_name(
            Some(match config.position() {
                "top" => "pan-down-symbolic",
                "left" => "pan-end-symbolic",
                "right" => "pan-start-symbolic",
                _ => "pan-up-symbolic",
            }),
            gtk::IconSize::Button,
        )));
        arrow.set_tooltip_text(Some(crate::i18n::text("隐藏的图标", "Hidden icons")));
        let popup = gtk::Popover::new(Some(&arrow));
        popup.style_context().add_class("adws-tray-overflow");
        popup.set_position(match config.position() {
            "top" => gtk::PositionType::Bottom,
            "left" => gtk::PositionType::Right,
            "right" => gtk::PositionType::Left,
            _ => gtk::PositionType::Top,
        });
        let grid = gtk::Grid::new();
        grid.set_row_spacing(8);
        grid.set_column_spacing(8);
        grid.set_margin_top(10);
        grid.set_margin_bottom(10);
        grid.set_margin_start(10);
        grid.set_margin_end(10);
        popup.add(&grid);
        arrow.set_popover(Some(&popup));
        arrow.set_no_show_all(true);
        bar.pack_end(&arrow, false, false, 0);
        bar.show_all();
        arrow.hide();
        let arrow_tip=TrayTip::new(arrow.upcast_ref(),config.position());
        let tray = Rc::new(Self {
            bar,
            grid,
            arrow,
            popup,
            focus_handler: RefCell::new(None),
            keyboard_focus: RefCell::new(None),
            _arrow_tip: arrow_tip,
            edge: config.position().to_owned(),
            items: RefCell::new(HashMap::new()),
            order: RefCell::new(vec![]),
            size: (config.thickness() as i32 / 2).clamp(16, 32),
            tasks: RefCell::new(Tasks::default()),
            bus: RefCell::new(None),
            registrations: RefCell::new(vec![]),
            owners: RefCell::new(vec![]),
            signals: RefCell::new(vec![]),
            watcher_items: Arc::new(Mutex::new(vec![])),
        });
        // A layer surface must become keyboard-interactive BEFORE the opening
        // pointer press reaches the compositor. Changing it in show is too
        // late: no focus is granted, so an outside click has no focus to revoke.
        let weak = Rc::downgrade(&tray);
        tray.arrow.connect_enter_notify_event(move |_, _| {
            if let Some(tray) = weak.upgrade() {
                tray.prepare_keyboard_focus();
            }
            glib::Propagation::Proceed
        });
        let weak = Rc::downgrade(&tray);
        tray.arrow.connect_leave_notify_event(move |_, _| {
            if let Some(tray) = weak.upgrade() && !tray.popup.is_visible() {
                tray.keyboard_focus.borrow_mut().take();
            }
            glib::Propagation::Proceed
        });
        let weak = Rc::downgrade(&tray);
        tray.popup.connect_show(move |_| {
            if let Some(tray) = weak.upgrade() {
                // The module can be created before Waybar attaches it to a
                // window. Resolve the host each time the overflow is opened.
                if let Some(window) = tray.bar.toplevel().and_then(|w| w.downcast::<gtk::Window>().ok()) {
                    tray.prepare_keyboard_focus();
                    let weak = Rc::downgrade(&tray);
                    let id = window.connect_focus_out_event(move |_, _| {
                        if let Some(tray) = weak.upgrade() { tray.popup.popdown(); }
                        glib::Propagation::Proceed
                    });
                    tray.focus_handler.replace(Some((window.downgrade(), id)));
                }
            }
        });
        let weak = Rc::downgrade(&tray);
        tray.popup.connect_unmap(move |_| {
            if let Some(tray) = weak.upgrade() { tray.disconnect_focus_handler(); }
        });
        let weak = Rc::downgrade(&tray);
        tray.tasks
            .borrow_mut()
            .0
            .push(glib::spawn_future_local(async move {
                if let Ok(bus) = gio::bus_get_future(gio::BusType::Session).await
                    && let Some(tray) = weak.upgrade()
                {
                    tray.connect(bus);
                }
            }));
        tray
    }
    fn prepare_keyboard_focus(&self) {
        if self.keyboard_focus.borrow().is_none()
            && let Some(window) = self.bar.toplevel().and_then(|w| w.downcast::<gtk::Window>().ok())
        {
            self.keyboard_focus.replace(crate::button::popup_keyboard_focus(&window));
        }
    }
    fn disconnect_focus_handler(&self) {
        if let Some((window, id)) = self.focus_handler.borrow_mut().take()
            && let Some(window) = window.upgrade()
        {
            window.disconnect(id);
        }
        self.keyboard_focus.borrow_mut().take();
    }
    fn connect(self: &Rc<Self>, bus: gio::DBusConnection) {
        self.bus.replace(Some(bus.clone()));
        let (tx, rx) = async_channel::bounded::<String>(256);
        let state = self.watcher_items.clone();
        let shared = state.clone();
        let send = tx.clone();
        let info = gio::DBusNodeInfo::for_xml(XML)
            .unwrap()
            .lookup_interface(WATCHER)
            .unwrap();
        if let Ok(reg) = bus.register_object(
            WP,
            &info,
            move |conn, sender, _, _, method, args, call| {
                if method == "RegisterStatusNotifierItem" {
                    let input = args.child_value(0).str().unwrap_or("").to_owned();
                    let address = if input.starts_with('/') {
                        format!("{sender}{input}")
                    } else if input.contains('/') {
                        input
                    } else {
                        format!("{input}/StatusNotifierItem")
                    };
                    if split_address(&address).is_none() {
                        call.return_dbus_error(
                            "org.freedesktop.DBus.Error.InvalidArgs",
                            "Invalid notifier address",
                        );
                        return;
                    }
                    let mut items = shared.lock().unwrap();
                    if !items.contains(&address) {
                        items.push(address.clone());
                        let _ = send.try_send(address.clone());
                        let _ = conn.emit_signal(
                            None,
                            WP,
                            WATCHER,
                            "StatusNotifierItemRegistered",
                            Some(&(address,).to_variant()),
                        );
                    }
                } else if method == "RegisterStatusNotifierHost" {
                    let _ =
                        conn.emit_signal(None, WP, WATCHER, "StatusNotifierHostRegistered", None);
                }
                call.return_value(Some(&().to_variant()));
            },
            move |_, _, _, _, property| match property {
                "RegisteredStatusNotifierItems" => state.lock().unwrap().clone().to_variant(),
                "IsStatusNotifierHostRegistered" => true.to_variant(),
                _ => 0i32.to_variant(),
            },
            |_, _, _, _, _, _| false,
        ) {
            self.registrations.borrow_mut().push(reg);
        }
        let send = tx.clone();
        self.owners
            .borrow_mut()
            .push(gio::bus_own_name_on_connection(
                &bus,
                WATCHER,
                gio::BusNameOwnerFlags::NONE,
                move |_, _| {
                    let _ = send.try_send("@watcher".into());
                },
                |_, _| {},
            ));
        let send = tx.clone();
        self.signals.borrow_mut().push(bus.signal_subscribe(
            Some(WATCHER),
            Some(WATCHER),
            Some("StatusNotifierItemRegistered"),
            Some(WP),
            None,
            gio::DBusSignalFlags::NONE,
            move |_, _, _, _, _, args| {
                if let Some(value) = args.child_value(0).str() {
                    let _ = send.try_send(value.to_string());
                }
            },
        ));
        let weak = Rc::downgrade(self);
        self.signals.borrow_mut().push(bus.signal_subscribe(
            Some(WATCHER),
            Some(WATCHER),
            Some("StatusNotifierItemUnregistered"),
            Some(WP),
            None,
            gio::DBusSignalFlags::NONE,
            move |_, _, _, _, _, args| {
                if let Some(tray) = weak.upgrade()
                    && let Some(value) = args.child_value(0).str()
                {
                    let id = if value.contains('/') {
                        value.to_owned()
                    } else {
                        format!("{value}/StatusNotifierItem")
                    };
                    if let Some(item) = tray.items.borrow_mut().remove(&id)
                        && let Some(parent) = item
                            .button
                            .parent()
                            .and_then(|p| p.downcast::<gtk::Container>().ok())
                    {
                        parent.remove(&item.button);
                    }
                    tray.order.borrow_mut().retain(|v| v != &id);
                    tray.arrange();
                }
            },
        ));
        let weak = Rc::downgrade(self);
        self.signals.borrow_mut().push(bus.signal_subscribe(
            Some("org.freedesktop.DBus"),
            Some("org.freedesktop.DBus"),
            Some("NameOwnerChanged"),
            Some("/org/freedesktop/DBus"),
            None,
            gio::DBusSignalFlags::NONE,
            move |_, _, _, _, _, args| {
                let name = args.child_value(0).str().unwrap_or("").to_owned();
                let old = args.child_value(1).str().unwrap_or("").to_owned();
                let new = args.child_value(2).str().unwrap_or("").to_owned();
                if let Some(tray) = weak.upgrade() {
                    if name == WATCHER && !new.is_empty() {
                        let _ = tx.try_send("@watcher".into());
                    } else if name.starts_with("org.kde.StatusNotifierItem-") && !new.is_empty() {
                        // Some Qt applications keep their SNI service but miss
                        // registration after the watcher/host is restarted.
                        let _ = tx.try_send(format!("{name}/StatusNotifierItem"));
                    }
                    if !old.is_empty() && new.is_empty() {
                        tray_remove(&tray, &name);
                    }
                }
            },
        ));
        let weak = Rc::downgrade(self);
        self.tasks
            .borrow_mut()
            .0
            .push(glib::spawn_future_local(async move {
                while let Ok(address) = rx.recv().await {
                    let Some(tray) = weak.upgrade() else { break };
                    if address == "@watcher" {
                        drop(tray);
                        if let Ok(proxy) = gio::DBusProxy::for_bus_future(
                            gio::BusType::Session,
                            gio::DBusProxyFlags::DO_NOT_AUTO_START,
                            None,
                            WATCHER,
                            WP,
                            WATCHER,
                        )
                        .await
                        {
                            let items = proxy
                                .cached_property("RegisteredStatusNotifierItems")
                                .and_then(|v| v.get::<Vec<String>>())
                                .unwrap_or_default();
                            let host = proxy
                                .connection()
                                .unique_name()
                                .map(|s| s.to_string())
                                .unwrap_or_default();
                            let _ = proxy
                                .call_future(
                                    "RegisterStatusNotifierHost",
                                    Some(&(host,).to_variant()),
                                    gio::DBusCallFlags::NONE,
                                    1200,
                                )
                                .await;
                            for item in items {
                                add_item(&weak, &item).await;
                            }
                        }
                    } else {
                        drop(tray);
                        add_item(&weak, &address).await;
                    }
                }
            }));
        // Existing watcher may predate this host, so fetch its current inventory.
        let weak = Rc::downgrade(self);
        self.tasks
            .borrow_mut()
            .0
            .push(glib::spawn_future_local(async move {
                if let Ok(proxy) = gio::DBusProxy::for_bus_future(
                    gio::BusType::Session,
                    gio::DBusProxyFlags::DO_NOT_AUTO_START,
                    None,
                    WATCHER,
                    WP,
                    WATCHER,
                )
                .await
                {
                    let items = proxy
                        .cached_property("RegisteredStatusNotifierItems")
                        .and_then(|v| v.get::<Vec<String>>())
                        .unwrap_or_default();
                    let host = proxy
                        .connection()
                        .unique_name()
                        .map(|s| s.to_string())
                        .unwrap_or_default();
                    let _ = proxy
                        .call_future(
                            "RegisterStatusNotifierHost",
                            Some(&(host,).to_variant()),
                            gio::DBusCallFlags::NONE,
                            1200,
                        )
                        .await;
                    for item in items {
                        add_item(&weak, &item).await;
                    }
                }
                // Recover live, standard SNI services omitted from the watcher
                // inventory. Query asynchronously; never scan processes or poll.
                if let Some(tray) = weak.upgrade() {
                    let bus = tray.bus.borrow().clone();
                    drop(tray);
                    if let Some(bus) = bus {
                        if let Ok(reply) = bus.call_future(
                            Some("org.freedesktop.DBus"), "/org/freedesktop/DBus",
                            "org.freedesktop.DBus", "ListNames", None, None,
                            gio::DBusCallFlags::NO_AUTO_START, 1500,
                        ).await {
                            if let Some(names) = reply.child_value(0).get::<Vec<String>>() {
                                for name in names.into_iter().filter(|name| name.starts_with("org.kde.StatusNotifierItem-")) {
                                    add_item(&weak, &format!("{name}/StatusNotifierItem")).await;
                                }
                            }
                        }
                    }
                }
            }));
    }
    fn arrange(&self) {
        let items = self.items.borrow();
        let order = self.order.borrow();
        let visible: Vec<_> = order
            .iter()
            .filter_map(|id| items.get(id))
            .filter(|item| item.active.get())
            .collect();
        for item in items.values() {
            if let Some(parent) = item
                .button
                .parent()
                .and_then(|p| p.downcast::<gtk::Container>().ok())
            {
                parent.remove(&item.button);
            }
            item.button.hide();
        }
        for (i, item) in visible.iter().enumerate() {
            if i < 3 {
                self.bar.pack_start(&item.button, false, false, 0);
                self.bar.reorder_child(&item.button, i as i32);
            } else {
                self.grid.attach(
                    &item.button,
                    ((i - 3) % 4) as i32,
                    ((i - 3) / 4) as i32,
                    1,
                    1,
                );
            }
            item.button.show_all();
        }
        if visible.len() > 3 {
            self.arrow.show();
        } else {
            self.popup.popdown();
            self.arrow.hide();
        }
        self.grid.show();
    }
}
fn tray_remove(tray: &Rc<Tray>, service: &str) {
    let removed: Vec<String> = tray
        .items
        .borrow()
        .iter()
        .filter(|(_, item)| {
            item.proxy.name().as_deref() == Some(service)
                || item.proxy.name_owner().as_deref() == Some(service)
        })
        .map(|(id, _)| id.clone())
        .collect();
    for id in removed {
        if let Some(item) = tray.items.borrow_mut().remove(&id) {
            if let Some(parent) = item
                .button
                .parent()
                .and_then(|p| p.downcast::<gtk::Container>().ok())
            {
                parent.remove(&item.button);
            }
        }
        tray.order.borrow_mut().retain(|v| v != &id);
        tray.watcher_items.lock().unwrap().retain(|v| v != &id);
        if let Some(bus) = tray.bus.borrow().as_ref() {
            let _ = bus.emit_signal(
                None,
                WP,
                WATCHER,
                "StatusNotifierItemUnregistered",
                Some(&(id,).to_variant()),
            );
        }
    }
    tray.arrange();
}
fn split_address(address: &str) -> Option<(&str, &str)> {
    let (name, rest) = address.split_once('/')?;
    let path = &address[name.len()..];
    if !gio::dbus_is_name(name) || !glib::Variant::is_object_path(path) || rest.is_empty() {
        None
    } else {
        Some((name, path))
    }
}
async fn add_item(weak: &std::rc::Weak<Tray>, address: &str) {
    let canonical = if address.contains('/') {
        address.to_string()
    } else {
        format!("{address}/StatusNotifierItem")
    };
    let address = canonical.as_str();
    let Some((service, path)) = split_address(address) else {
        return;
    };
    if weak
        .upgrade()
        .is_none_or(|s| s.items.borrow().contains_key(address))
    {
        return;
    }
    let Ok(proxy) = gio::DBusProxy::for_bus_future(
        gio::BusType::Session,
        gio::DBusProxyFlags::DO_NOT_AUTO_START,
        None,
        service,
        path,
        ITEM,
    )
    .await
    else {
        return;
    };
    if proxy.name_owner().is_none() {
        return;
    }
    let Some(tray) = weak.upgrade() else { return };
    if tray.items.borrow().contains_key(address)
        || tray.items.borrow().values().any(|item|
            item.proxy.name_owner() == proxy.name_owner()
                && item.proxy.object_path() == proxy.object_path())
    {
        return;
    }
    let button = gtk::Button::new();
    button.set_relief(gtk::ReliefStyle::None);
    button.style_context().add_class("adws-tray-item");
    let image = gtk::Image::new();
    image.set_pixel_size(tray.size);
    button.add(&image);
    let tip=TrayTip::new(&button,&tray.edge);
    let item = Rc::new(Item {
        button,
        _tip: tip,
        image,
        proxy,
        active: Cell::new(false),
        menu: RefCell::new(None),
        refresh: RefCell::new(None),
        refresh_dirty: Cell::new(false),
        handlers: RefCell::new(Vec::new()),
        size: tray.size,
        icon_theme: RefCell::new(None),
        icon_properties: RefCell::new(HashMap::new()),
        icon_signature: RefCell::new(None),
    });
    let wi=Rc::downgrade(&item);
    item.image.connect_style_updated(move |_| {
        if let Some(item)=wi.upgrade() { render_icon(&item,&item.icon_properties.borrow()); }
    });
    let wi=Rc::downgrade(&item);
    item.image.connect_scale_factor_notify(move |_| {
        if let Some(item)=wi.upgrade() { render_icon(&item,&item.icon_properties.borrow()); }
    });
    // Some clients only emit the standard PropertiesChanged notification.
    // Both paths use the same bounded refresh queue and weak ownership.
    for signal in ["g-signal", "g-properties-changed"] {
        let wi = Rc::downgrade(&item);
        let wt = weak.clone();
        item.handlers.borrow_mut().push(item.proxy.connect_local(signal, false, move |_| {
            refresh(&wi, &wt);
            None
        }));
    }
    let wi = Rc::downgrade(&item);
    item.button.connect_button_press_event(move |_, event| {
        let Some(item) = wi.upgrade() else {
            return glib::Propagation::Proceed;
        };
        let (x, y) = event.root();
        let args = (x as i32, y as i32).to_variant();
        let method = match event.button() {
            1 => {
                if item
                    .proxy
                    .cached_property("ItemIsMenu")
                    .and_then(|v| v.get::<bool>())
                    .unwrap_or(false)
                {
                    "ContextMenu"
                } else {
                    "Activate"
                }
            }
            2 => "SecondaryActivate",
            3 => "ContextMenu",
            _ => return glib::Propagation::Proceed,
        };
        if method == "ContextMenu"
            && let Some(menu) = item.menu.borrow().as_ref()
            && !menu.children().is_empty()
        {
            crate::menu_style::apply(menu);
            menu.show_all();
            menu.popup_at_pointer(Some(event));
            return glib::Propagation::Stop;
        }
        item.proxy.call(
            method,
            Some(&args),
            gio::DBusCallFlags::NONE,
            1200,
            gio::Cancellable::NONE,
            |_| {},
        );
        glib::Propagation::Stop
    });
    tray.order.borrow_mut().push(address.to_owned());
    tray.items
        .borrow_mut()
        .insert(address.to_owned(), item.clone());
    drop(tray);
    refresh(&Rc::downgrade(&item), weak);
}
fn refresh(wi: &std::rc::Weak<Item>, wt: &std::rc::Weak<Tray>) {
    let Some(item) = wi.upgrade() else { return };
    if item.refresh.borrow().is_some() {
        item.refresh_dirty.set(true);
        return;
    }
    item.refresh_dirty.set(false);
    let wi = wi.clone();
    let wt = wt.clone();
    let proxy = item.proxy.clone();
    let task = glib::spawn_future_local(async move {
        glib::timeout_future(std::time::Duration::from_millis(40)).await;
        let result = proxy
            .connection()
            .call_future(
                proxy.name().as_deref(),
                &proxy.object_path(),
                "org.freedesktop.DBus.Properties",
                "GetAll",
                Some(&(ITEM,).to_variant()),
                None,
                gio::DBusCallFlags::NO_AUTO_START,
                1500,
            )
            .await;
        let reply = match result {
            Ok(reply) => reply,
            Err(error) => {
                tracing::debug!(%error,"cannot refresh tray item");
                finish_refresh(&wi, &wt);
                return;
            }
        };
        let Some(item) = wi.upgrade() else { return };
        let Some(tray) = wt.upgrade() else { return };
        let props = reply
            .child_value(0)
            .get::<HashMap<String, glib::Variant>>()
            .unwrap_or_default();
        let get = |key: &str| props.get(key).and_then(|v| v.str()).unwrap_or("");
        let status = get("Status");
        let old_active = item.active.replace(status != "Passive");
        let title = get("Title");
        item.button
            .set_tooltip_text(Some(if title.is_empty() { get("Id") } else { title }));
        item.button.set_has_tooltip(false);
        item.icon_properties.replace(props.clone());
        render_icon(&item,&props);
        if item.menu.borrow().is_none()
            && let Some(path) = props.get("Menu").and_then(|v| v.str())
            && path != "/"
            && glib::Variant::is_object_path(path)
        {
            if let Some(name) = proxy.name() {
                item.menu.replace(native_menu(&name, path));
            }
        }
        if old_active != item.active.get() {
            tray.arrange();
        }
        drop(tray);
        drop(item);
        finish_refresh(&wi, &wt);
    });
    item.refresh.replace(Some(task));
}
fn finish_refresh(wi: &std::rc::Weak<Item>, wt: &std::rc::Weak<Tray>) {
    let Some(item) = wi.upgrade() else { return };
    item.refresh.borrow_mut().take();
    if item.refresh_dirty.replace(false) && wt.upgrade().is_some() {
        drop(item);
        refresh(wi, wt);
    }
}
fn render_icon(item: &Item, props: &HashMap<String,glib::Variant>) {
    if props.is_empty() {return;}
    let get = |key:&str| props.get(key).and_then(|v|v.str()).unwrap_or("");
    let status=get("Status");
    let signature=(["Status","IconName","IconPixmap","IconThemePath","AttentionIconName","AttentionIconPixmap","OverlayIconName","OverlayIconPixmap"].iter().map(|key|props.get(*key).cloned()).collect(),
        item.image.scale_factor(),item.image.style_context().color(gtk::StateFlags::NORMAL));
    if item.icon_signature.borrow().as_ref()==Some(&signature) {return;}
        let scale = item.image.scale_factor().max(1);
        let size = item.size * scale;
        let theme_path = get("IconThemePath");
        let theme = if theme_path.is_empty() {
            gtk::IconTheme::default().unwrap_or_default()
        } else {
            let mut cache = item.icon_theme.borrow_mut();
            if cache.as_ref().is_none_or(|(path,_)| path != theme_path) {
                let theme = gtk::IconTheme::new();
                if let Some(settings) = gtk::Settings::default() {
                    let name: String = settings.property("gtk-icon-theme-name");
                    theme.set_custom_theme(Some(&name));
                }
                theme.prepend_search_path(theme_path);
                *cache = Some((theme_path.to_owned(), theme));
            }
            cache.as_ref().unwrap().1.clone()
        };
        let image = if status == "NeedsAttention" {
            resolve_icon(&props, "AttentionIcon", &theme, size, Some(&item.image.style_context()))
                .or_else(|| resolve_icon(&props, "Icon", &theme, size, Some(&item.image.style_context())))
        } else { resolve_icon(&props, "Icon", &theme, size, Some(&item.image.style_context())) };
        if let Some(image) = image {
            if let Some(overlay) = resolve_icon(&props, "OverlayIcon", &theme, (size/2).max(1), Some(&item.image.style_context())) {
                let width=overlay.width().min(size); let height=overlay.height().min(size);
                overlay.composite(&image,size-width,size-height,width,height,
                    f64::from(size-width),f64::from(size-height),1.,1.,gtk::gdk_pixbuf::InterpType::Bilinear,255);
            }
            if let Some(surface) = image.create_surface(scale,item.button.window().as_ref()) {
                item.image.set_from_surface(Some(&surface));
                item.icon_signature.replace(Some(signature));
            }
        } else if item.image.storage_type() == gtk::ImageType::Empty {
            // Temporary file/pixmap failures must not erase a valid icon or
            // cache the failure forever. The next identical signal can retry.
            item.image.set_from_icon_name(Some("application-x-executable-symbolic"),gtk::IconSize::Button);
        }

}

fn resolve_icon(props: &HashMap<String,glib::Variant>, prefix: &str,
                theme: &gtk::IconTheme, size: i32, context: Option<&gtk::StyleContext>) -> Option<gtk::gdk_pixbuf::Pixbuf> {
    let name=props.get(&format!("{prefix}Name")).and_then(|v|v.str()).unwrap_or("");
    let from_name = if std::path::Path::new(name).is_absolute() {
        gtk::gdk_pixbuf::Pixbuf::from_file_at_scale(name,size,size,true).ok()
    } else if !name.is_empty() {
        // A non-empty but unavailable IconName must still fall back to pixmaps.
        theme.lookup_icon(name,size,gtk::IconLookupFlags::FORCE_SIZE).and_then(|info| {
            if info.is_symbolic() && context.is_some() {
                info.load_symbolic_for_context(context.unwrap()).ok().map(|(pix,_)|pix)
            } else {info.load_icon().ok()}
        })
    } else {None};
    from_name.and_then(|pix|fit_pixbuf(&pix,size)).or_else(||props.get(&format!("{prefix}Pixmap")).and_then(|v|pixmap(v,size)))
}

fn pixmap(value: &glib::Variant, size: i32) -> Option<gtk::gdk_pixbuf::Pixbuf> {
    let pixmaps = value.get::<Vec<(i32, i32, Vec<u8>)>>()?;
    let (w, h, mut data) = pixmaps
        .into_iter()
        .filter(|(w, h, d)| {
            *w > 0
                && *h > 0
                && *w <= 1024
                && *h <= 1024
                && d.len() == (*w as usize) * (*h as usize) * 4
        })
        .min_by_key(|(w, h, _)| (*w - size).abs() + (*h - size).abs())?;
    for pixel in data.chunks_exact_mut(4) {
        pixel.rotate_left(1);
    }
    let bytes = glib::Bytes::from_owned(data);
    let pix = gtk::gdk_pixbuf::Pixbuf::from_bytes(
        &bytes,
        gtk::gdk_pixbuf::Colorspace::Rgb,
        true,
        8,
        w,
        h,
        w * 4,
    );
    fit_pixbuf(&pix,size)
}
fn fit_pixbuf(pix: &gtk::gdk_pixbuf::Pixbuf, size:i32) -> Option<gtk::gdk_pixbuf::Pixbuf> {
    if pix.width()==size && pix.height()==size {return Some(pix.clone());}
    let ratio=f64::from(size)/f64::from(pix.width().max(pix.height()));
    let width=(f64::from(pix.width())*ratio).round().max(1.) as i32;
    let height=(f64::from(pix.height())*ratio).round().max(1.) as i32;
    let scaled=pix.scale_simple(width,height,gtk::gdk_pixbuf::InterpType::Bilinear)?;
    let canvas=gtk::gdk_pixbuf::Pixbuf::new(gtk::gdk_pixbuf::Colorspace::Rgb,true,8,size,size)?;
    canvas.fill(0);
    scaled.copy_area(0,0,width,height,&canvas,(size-width)/2,(size-height)/2);
    Some(canvas)
}

#[link(name = "dl")]
unsafe extern "C" {
    fn dlopen(name: *const i8, flags: i32) -> *mut c_void;
    fn dlsym(handle: *mut c_void, name: *const i8) -> *mut c_void;
}
fn native_menu(bus: &str, path: &str) -> Option<gtk::Menu> {
    type New = unsafe extern "C" fn(*const i8, *const i8) -> *mut gtk::ffi::GtkWidget;
    type Client = unsafe extern "C" fn(*mut gtk::ffi::GtkWidget) -> *mut c_void;
    type Accel = unsafe extern "C" fn(*mut c_void, *mut gtk::ffi::GtkAccelGroup);
    static LIB: OnceLock<usize> = OnceLock::new();
    let handle = *LIB
        .get_or_init(|| unsafe { dlopen(c"libdbusmenu-gtk3.so.4".as_ptr(), 1) as usize })
        as *mut c_void;
    if handle.is_null() {
        return None;
    }
    let bus = CString::new(bus).ok()?;
    let path = CString::new(path).ok()?;
    unsafe {
        let symbol = dlsym(handle, c"dbusmenu_gtkmenu_new".as_ptr());
        if symbol.is_null() {
            return None;
        }
        let new: New = std::mem::transmute(symbol);
        let widget = new(bus.as_ptr(), path.as_ptr());
        if widget.is_null() {
            return None;
        }
        let menu: gtk::Widget = from_glib_none(widget);
        let menu = menu.downcast::<gtk::Menu>().ok()?;
        let client = dlsym(handle, c"dbusmenu_gtkmenu_get_client".as_ptr());
        let accel = dlsym(handle, c"dbusmenu_gtkclient_set_accel_group".as_ptr());
        if !client.is_null() && !accel.is_null() {
            let get: Client = std::mem::transmute(client);
            let set: Accel = std::mem::transmute(accel);
            let group = gtk::AccelGroup::new();
            set(get(widget), group.to_glib_none().0);
        }
        Some(menu)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn addresses_are_validated() {
        assert!(split_address("org.test.Item/StatusNotifierItem").is_some());
        assert!(split_address(":1.10/StatusNotifierItem").is_some());
        assert!(split_address("bad name/x").is_none());
        assert!(split_address("org.test.Item/not-valid").is_none());
    }
}

#[cfg(test)]
mod gui_tests {
    use super::*;
    use std::time::Duration;
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn icon_paths_pixmap_fallback_and_aspect_ratio() {
        gtk::init().unwrap();
        let theme=gtk::IconTheme::default().unwrap();
        let pix=gtk::gdk_pixbuf::Pixbuf::new(gtk::gdk_pixbuf::Colorspace::Rgb,true,8,20,10).unwrap();
        pix.fill(0xff0000ff);
        let path=std::env::temp_dir().join(format!("adws-tray-icon-{}.png",std::process::id()));
        pix.savev(&path,"png",&[]).unwrap();
        let mut props=HashMap::new();
        props.insert("IconName".into(),path.to_string_lossy().to_variant());
        let file=resolve_icon(&props,"Icon",&theme,32,None).unwrap();
        assert_eq!((file.width(),file.height()),(32,32));
        assert_eq!(&file.read_pixel_bytes().as_ref()[..4],&[0,0,0,0]);
        props.insert("IconName".into(),"adws-deliberately-unavailable-icon".to_variant());
        props.insert("IconPixmap".into(),vec![(20,10,[255u8,255,0,0].repeat(200))].to_variant());
        let fallback=resolve_icon(&props,"Icon",&theme,32,None).unwrap();
        assert_eq!((fallback.width(),fallback.height()),(32,32));
        let bytes=fallback.read_pixel_bytes();let row=fallback.rowstride() as usize;
        assert_eq!(&bytes.as_ref()[..4],&[0,0,0,0],"letterboxing must stay transparent");
        assert_eq!(&bytes.as_ref()[8*row..8*row+4],&[255,0,0,255],"ARGB must become RGBA without tinting");
        props.insert("IconPixmap".into(),vec![(20,10,vec![0u8;3])].to_variant());
        assert!(resolve_icon(&props,"Icon",&theme,32,None).is_none());
        std::fs::remove_file(path).unwrap();
    }
    const ITEM_XML: &str = r#"<node><interface name="org.kde.StatusNotifierItem"><method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method><method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method><property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/><property name="IconName" type="s" access="read"/><property name="ItemIsMenu" type="b" access="read"/></interface></node>"#;
    #[test]
    #[ignore = "requires isolated GTK and session bus"]
    fn existing_unregistered_sni_is_recovered_and_not_duplicated() {
        gtk::init().unwrap();
        let context = glib::MainContext::default();
        let _guard = context.acquire().unwrap();
        let bus = context.block_on(gio::bus_get_future(gio::BusType::Session)).unwrap();
        let iface = gio::DBusNodeInfo::for_xml(ITEM_XML).unwrap().lookup_interface(ITEM).unwrap();
        let reads = Arc::new(std::sync::atomic::AtomicU32::new(0));
        let getter_reads = reads.clone();
        let passive = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let getter_passive = passive.clone();
        let reg = bus.register_object("/StatusNotifierItem", &iface,
            |_,_,_,_,_,_,call| call.return_value(Some(&().to_variant())),
            move |_,_,_,_,property| match property {
                "Title" => { getter_reads.fetch_add(1,std::sync::atomic::Ordering::Relaxed); if getter_passive.load(std::sync::atomic::Ordering::Relaxed) { "WeChat hidden" } else { "WeChat fixture" }.to_variant() },
                "Status" => if getter_passive.load(std::sync::atomic::Ordering::Relaxed) { "Passive" } else { "Active" }.to_variant(),
                "ItemIsMenu" => false.to_variant(),
                _ => "audio-volume-high-symbolic".to_variant(),
            }, |_,_,_,_,_,_| false).unwrap();
        let name = "org.kde.StatusNotifierItem-12345-9";
        let owner = gio::bus_own_name_on_connection(&bus, name, gio::BusNameOwnerFlags::NONE, |_,_|{}, |_,_|{});
        context.block_on(glib::timeout_future(Duration::from_millis(80)));
        let root = gtk::Box::new(gtk::Orientation::Horizontal,0);
        let config:Config=serde_json::from_str(r#"{"component":"tray"}"#).unwrap();
        let tray = Tray::new(root.upcast_ref(), &config);
        context.block_on(glib::timeout_future(Duration::from_millis(250)));
        assert_eq!(tray.items.borrow().len(),1,"live SNI must recover without registration");
        assert!(tray.items.borrow().values().next().unwrap().active.get());
        let item = tray.items.borrow().values().next().unwrap().clone();
        let icon_path = std::env::temp_dir().join(format!("adws-late-icon-{}.png",std::process::id()));
        let props = HashMap::from([("IconName".into(),icon_path.to_string_lossy().to_variant())]);
        let prior_signature = item.icon_signature.borrow().clone();
        render_icon(&item,&props);
        assert_eq!(*item.icon_signature.borrow(),prior_signature,"missing icon must not cache failure");
        let pixels = gtk::gdk_pixbuf::Pixbuf::new(gtk::gdk_pixbuf::Colorspace::Rgb,true,8,16,16).unwrap();
        pixels.fill(0x00ff00ff);pixels.savev(&icon_path,"png",&[]).unwrap();
        render_icon(&item,&props);
        assert_ne!(*item.icon_signature.borrow(),prior_signature,"same properties must retry newly available icon");
        std::fs::remove_file(icon_path).unwrap();
        let reads_before = reads.load(std::sync::atomic::Ordering::Relaxed);
        for _ in 0..40 {
            refresh(&Rc::downgrade(&item), &Rc::downgrade(&tray));
            context.block_on(glib::timeout_future(Duration::from_millis(10)));
        }
        assert!(reads.load(std::sync::atomic::Ordering::Relaxed) > reads_before, "continuous signals must not starve GetAll");
        context.block_on(glib::timeout_future(Duration::from_millis(150)));
        assert!(item.refresh.borrow().is_none(), "completed requests must release their task");
        for hidden in [true, false] {
            passive.store(hidden,std::sync::atomic::Ordering::Relaxed);
            let changed = HashMap::from([("Status",if hidden { "Passive" } else { "Active" }.to_variant())]);
            bus.emit_signal(None,"/StatusNotifierItem","org.freedesktop.DBus.Properties",
                "PropertiesChanged",Some(&(ITEM,changed,Vec::<String>::new()).to_variant())).unwrap();
            context.block_on(glib::timeout_future(Duration::from_millis(150)));
            assert_eq!(item.active.get(),!hidden,"standard property updates must refresh tray visibility");
            assert_eq!(item.button.tooltip_text().as_deref(),Some(if hidden { "WeChat hidden" } else { "WeChat fixture" }),"property refresh must also update descriptions");
        }
        drop(item);
        context.block_on(add_item(&Rc::downgrade(&tray), &format!("{}/StatusNotifierItem", bus.unique_name().unwrap())));
        assert_eq!(tray.items.borrow().len(),1,"service aliases must not duplicate icons");
        gio::bus_unown_name(owner);
        context.block_on(glib::timeout_future(Duration::from_millis(100)));
        assert!(tray.items.borrow().is_empty(),"a withdrawn service must still disappear");
        drop(tray);
        bus.unregister_object(reg).unwrap();
    }
    #[test]
    #[ignore = "requires nested Wayland compositor and real-input driver"]
    fn overflow_dismisses_on_external_wayland_click() {
        use std::time::Instant;
        #[link(name = "gtk-layer-shell")]
        unsafe extern "C" {
            fn gtk_layer_init_for_window(window: *mut gtk::ffi::GtkWindow);
            fn gtk_layer_set_anchor(window: *mut gtk::ffi::GtkWindow, edge: i32, anchor: i32);
            fn gtk_layer_set_layer(window: *mut gtk::ffi::GtkWindow, layer: i32);
            fn gtk_layer_get_keyboard_mode(window: *mut gtk::ffi::GtkWindow) -> i32;
        }
        gtk::init().unwrap();
        let context = glib::MainContext::default();
        let _guard = context.acquire().unwrap();
        let folder = std::path::PathBuf::from(std::env::var_os("ADWS_TRAY_TEST_DIR").unwrap());
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        unsafe {
            gtk_layer_init_for_window(window.to_glib_none().0);
            gtk_layer_set_layer(window.to_glib_none().0, 2);
            for edge in [0, 1, 3] { gtk_layer_set_anchor(window.to_glib_none().0, edge, 1); }
        }
        window.set_size_request(-1, 60);
        let root = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        window.add(&root);
        let config: Config = serde_json::from_str(r#"{"component":"tray"}"#).unwrap();
        let tray = Tray::new(root.upcast_ref(), &config);
        tray.bar.set_margin_start(300);
        window.show_all();
        let bus = context.block_on(gio::bus_get_future(gio::BusType::Session)).unwrap();
        let iface = gio::DBusNodeInfo::for_xml(ITEM_XML).unwrap().lookup_interface(ITEM).unwrap();
        let mut registrations = Vec::new();
        for i in 0..4 {
            let path = format!("/OverflowFixture{i}");
            registrations.push(bus.register_object(&path, &iface,
                |_,_,_,_,_,_,call| call.return_value(Some(&().to_variant())),
                move |_,_,_,_,property| match property {
                    "Title" => format!("Fixture {i}").to_variant(),
                    "Status" => "Active".to_variant(),
                    "ItemIsMenu" => false.to_variant(),
                    _ => "audio-volume-high-symbolic".to_variant(),
                }, |_,_,_,_,_,_| false).unwrap());
            context.block_on(add_item(&Rc::downgrade(&tray), &format!("{}{path}", bus.unique_name().unwrap())));
        }
        context.block_on(glib::timeout_future(Duration::from_millis(350)));
        assert!(tray.arrow.is_visible());
        let publish_position = || {
            let a = tray.arrow.allocation();
            let (x,y) = tray.arrow.translate_coordinates(&window,a.width()/2,a.height()/2).unwrap();
            std::fs::write(folder.join("ready.tmp"),serde_json::json!({"arrow":[x,y],"height":window.allocated_height()}).to_string()).unwrap();
            std::fs::rename(folder.join("ready.tmp"),folder.join("ready.json")).unwrap();
        };
        publish_position();
        let wait = |predicate: &dyn Fn() -> bool| {
            let until = Instant::now() + Duration::from_secs(8);
            while !predicate() {
                publish_position();
                assert!(Instant::now() < until, "timed out: mapped={}, active={}", tray.popup.is_mapped(), window.is_active());
                context.block_on(glib::timeout_future(Duration::from_millis(10)));
            }
        };
        for i in 0..3 {
            wait(&|| tray.popup.is_mapped());
            std::fs::write(folder.join("phase"), format!("open-{i}")).unwrap();
            wait(&|| !tray.popup.is_mapped());
            assert!(tray.focus_handler.borrow().is_none());
            assert_eq!(unsafe { gtk_layer_get_keyboard_mode(window.to_glib_none().0) }, 0, "closing must restore inert keyboard mode");
            std::fs::write(folder.join("phase"), format!("closed-{i}")).unwrap();
        }
        unsafe { window.destroy(); }
        for id in registrations { bus.unregister_object(id).unwrap(); }
    }
    #[test]
    #[ignore = "requires isolated GTK and session bus"]
    fn overflow_and_unload_are_bounded() {
        gtk::init().unwrap();
        let context = glib::MainContext::default();
        let _guard = context.acquire().unwrap();
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        let root = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        window.add(&root);
        let config: Config =
            serde_json::from_str(r#"{"component":"tray","position":"bottom","thickness":36}"#)
                .unwrap();
        let tray = Tray::new(root.upcast_ref(), &config);
        window.show_all();
        context.block_on(glib::timeout_future(Duration::from_millis(200)));
        let bus = context
            .block_on(gio::bus_get_future(gio::BusType::Session))
            .unwrap();
        let name = bus.unique_name().unwrap();
        let mut regs = vec![];
        let iface = gio::DBusNodeInfo::for_xml(ITEM_XML)
            .unwrap()
            .lookup_interface(ITEM)
            .unwrap();
        for i in 0..7 {
            let path = format!("/Item{i}");
            regs.push(
                bus.register_object(
                    &path,
                    &iface,
                    |_, _, _, _, _, _, call| call.return_value(Some(&().to_variant())),
                    move |_, _, _, _, property| match property {
                        "Title" => format!("Application {i}").to_variant(),
                        "Status" => "Active".to_variant(),
                        "ItemIsMenu" => false.to_variant(),
                        _ => "audio-volume-high-symbolic".to_variant(),
                    },
                    |_, _, _, _, _, _| false,
                )
                .unwrap(),
            );
            let address = format!("{name}{path}");
            context
                .block_on(bus.call_future(
                    Some(WATCHER),
                    WP,
                    WATCHER,
                    "RegisterStatusNotifierItem",
                    Some(&(address,).to_variant()),
                    None,
                    gio::DBusCallFlags::NONE,
                    1500,
                ))
                .unwrap();
        }
        context.block_on(glib::timeout_future(Duration::from_millis(500)));
        assert_eq!(tray.items.borrow().len(), 7);
        assert_eq!(tray.bar.children().len(), 4);
        assert_eq!(tray.grid.children().len(), 4);
        assert!(tray.arrow.is_visible());
        for item in tray.items.borrow().values() {
            assert!(!item.button.has_tooltip(), "native layer tooltip must stay disabled");
            assert_eq!(item._tip.popup.relative_to().unwrap(), item.button.clone().upcast::<gtk::Widget>(), "description must remain anchored after moving into overflow");
            assert_eq!(item._tip.popup.position(), gtk::PositionType::Top);
        }
        for _ in 0..3 {
            tray.popup.show_all();
            tray.popup.popup();
            context.block_on(glib::timeout_future(Duration::from_millis(200)));
            assert!(tray.popup.is_mapped(), "overflow must open normally");
            assert!(tray.focus_handler.borrow().is_some());
            let event = gtk::gdk::Event::new(gtk::gdk::EventType::FocusChange);
            window.emit_by_name::<bool>("focus-out-event", &[&event]);
            context.block_on(glib::timeout_future(Duration::from_millis(250)));
            assert!(!tray.popup.is_mapped(), "losing host focus must dismiss hidden icons");
            assert!(tray.focus_handler.borrow().is_none(), "closing must disconnect the host handler");
        }
        let weak = Rc::downgrade(&tray);
        let item_weak: Vec<_> = tray.items.borrow().values().map(Rc::downgrade).collect();
        for _ in 0..30 {
            for item in tray.items.borrow().values() {
                refresh(&Rc::downgrade(item), &weak);
            }
        }
        context.block_on(glib::timeout_future(Duration::from_millis(100)));
        assert_eq!(
            tray.tasks.borrow().0.len(),
            3,
            "refresh must not append tasks indefinitely"
        );
        tray_remove(&tray, &name);
        assert!(tray.items.borrow().is_empty());
        assert_eq!(tray.bar.children().len(), 1);
        assert!(!tray.arrow.is_visible());
        drop(tray);
        context.block_on(glib::timeout_future(Duration::from_millis(100)));
        assert!(weak.upgrade().is_none());
        assert!(item_weak.iter().all(|weak| weak.upgrade().is_none()));
        for reg in regs {
            bus.unregister_object(reg).unwrap();
        }
        unsafe {
            window.destroy();
        }
    }
}

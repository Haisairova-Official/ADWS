use std::{cell::RefCell, fmt::Debug, path::PathBuf, rc::Rc};

use waybar_cffi::gtk::{
    self as gtk, Border, CssProvider, IconLookupFlags, IconSize, IconTheme, ReliefStyle,
    StateFlags,
    gdk_pixbuf::Pixbuf,
    prelude::*,

};

use crate::state::State;

/// A taskbar button.
pub struct Button {
    app_id: Option<String>,
    button: gtk::Button,
    badge: gtk::DrawingArea,
    count: Rc<std::cell::Cell<usize>>,
    dots: Rc<std::cell::Cell<bool>>,
    recent_window: Rc<std::cell::Cell<u64>>,
    pub(crate) hover_popup: Rc<RefCell<Option<gtk::Popover>>>,
    #[cfg(test)]
    pub(crate) badge_test: gtk::DrawingArea,
    icon: gtk::Overlay,
    state: State,
    members: Rc<RefCell<Vec<(u64, String)>>>,
    hover: Rc<RefCell<Option<Rc<crate::hover::HoverPreview>>>>,
    styled_title: RefCell<Option<String>>,
}

impl Debug for Button {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Button")
            .field("app_id", &self.app_id)
            .finish()
    }
}

// These have to be declared as thread locals because Gtk objects are (generally) not Send.
// Practically, we're likely to be doing everything from the main thread anyway, but Glib can
// figure that out.
thread_local! {
    static BUTTON_CSS_PROVIDER: CssProvider = {
        let css = CssProvider::new();
        if let Err(e) = css.load_from_data(include_bytes!("style.css")) {
            tracing::error!(%e, "CSS parse error");
        }

        css
    };

    static ICON_THEME: IconTheme = {
        IconTheme::default().unwrap_or_default()
    };

    static ACTIVE_CONTEXT_MENU: RefCell<Option<gtk::Menu>> = RefCell::new(None);
}

impl Button {
    /// Instantiates a new button, including creating a new Gtk button internally.
    #[tracing::instrument(level = "TRACE", fields(app_id = &window.app_id))]
    pub fn new(state: &State, window: &niri_ipc::Window) -> Self {
        Self::create(state, window.app_id.clone(), window.id, window.title.clone().unwrap_or_default())
    }

    pub fn pinned(state: &State, pin: &crate::pins::Pin) -> Self {
        let button = Self::create(state, Some(pin.desktop_id.clone()), 0, pin.name.clone());
        button.button.set_tooltip_text(Some(&pin.name));
        button.set_group(vec![], 0);
        button
    }

    fn create(state: &State, app_id: Option<String>, window_id: u64, title: String) -> Self {
        let state = state.clone();

        // Set up the basic image button.
        //
        // Note that we don't actually set the image here: we need to know the size before doing so
        // in order to load the most appropriate icon from the icon theme, and we won't know that
        // until we get an actual size allocation.
        let button = gtk::Button::new();
        button.set_always_show_image(true);
        button.set_relief(ReliefStyle::None);
        let icon = gtk::Overlay::new();
        icon.add(&gtk::Image::from_icon_name(Some("application-x-executable"),IconSize::Button));
        let badge = gtk::DrawingArea::new();
        let count=Rc::new(std::cell::Cell::new(0usize));
        let diameter=(state.config().thickness()/state.config().rows()/2).clamp(8,20) as i32;
        badge.set_size_request(diameter,diameter);
        let number=count.clone();
        let dots=Rc::new(std::cell::Cell::new(false));
        let draw_dots=dots.clone();
        badge.connect_draw(move |widget,cr| {
            let size=widget.allocated_width().min(widget.allocated_height()) as f64;
            let style=widget.style_context();
            let bg=style.lookup_color("primary").or_else(||style.lookup_color("theme_selected_bg_color")).unwrap_or(gtk::gdk::RGBA::new(0.2,0.4,0.8,1.));
            let fg=style.lookup_color("on_primary").or_else(||style.lookup_color("theme_selected_fg_color")).unwrap_or(gtk::gdk::RGBA::new(1.,1.,1.,1.));
            cr.set_source_rgba(bg.red(),bg.green(),bg.blue(),1.);cr.arc(size/2.,size/2.,(size/2.-1.).max(1.),0.,std::f64::consts::TAU);let _=cr.fill_preserve();
            cr.set_source_rgba(fg.red(),fg.green(),fg.blue(),1.);cr.set_line_width(2.);let _=cr.stroke();
            if draw_dots.get() {
                // Solid circles give consistent weight and compact spacing
                // regardless of which fonts the user has installed.
                let radius = (size - 4.).max(1.) * 0.11;
                let step = radius * 2.5;
                for offset in [-step, 0., step] {
                    cr.new_sub_path();
                    cr.arc(size / 2. + offset, size / 2., radius, 0., std::f64::consts::TAU);
                }
                let _ = cr.fill();
            } else {
                let text=if number.get()>99{"99+".to_string()}else{number.get().to_string()};
                cr.select_font_face("Sans",gtk::cairo::FontSlant::Normal,gtk::cairo::FontWeight::Bold);
                cr.set_font_size(size*if text.len()>2{0.38}else{0.58});
                if let Ok(ext)=cr.text_extents(&text){cr.move_to((size-ext.width())/2.-ext.x_bearing(),(size-ext.height())/2.-ext.y_bearing());}
                cr.set_source_rgba(fg.red(),fg.green(),fg.blue(),1.);let _=cr.show_text(&text);
            }
            gtk::glib::Propagation::Stop
        });
        badge.style_context().add_class("adws-window-count");
        badge.set_halign(gtk::Align::End);
        badge.set_valign(gtk::Align::End);
        badge.set_no_show_all(true);
        icon.add_overlay(&badge);
        icon.set_overlay_pass_through(&badge,true);
        button.set_image(Some(&icon));

        // Provide the base CSS for each button that users can then extend.
        BUTTON_CSS_PROVIDER.with(|provider| {

            button
                .style_context()
                .add_provider(provider, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION - 1);
        });

        let button = Self {
            app_id,
            button,
            #[cfg(test)]
            badge_test: badge.clone(),
            hover_popup: Rc::new(RefCell::new(None)),
            hover: Rc::new(RefCell::new(None)),
            badge,
            count,
            dots,
            recent_window: Rc::new(std::cell::Cell::new(window_id)),
            icon,
            state,
            members: Rc::new(RefCell::new(vec![(window_id, title)])),
            styled_title: RefCell::new(None),
        };

        // Set up our event handlers. It's easier to do this with self already available.
        button.connect_click_handler(window_id);
        button.connect_context_menu(window_id);
        button.connect_hover_description();
        button.connect_size_allocate();
        let hover = button.hover.clone();
        button.button.connect_destroy(move |_| { hover.borrow_mut().take(); });

        button
    }

    pub fn dismiss_hover(&self) {
        if let Some(hover) = self.hover.borrow().as_ref() { hover.dismiss(); }
    }

    pub fn set_group(&self, members: Vec<(u64, String)>, recent_window: u64) {
        self.recent_window.set(recent_window);
        if *self.members.borrow() == members { return; }
        let count = members.len();
        self.count.set(count);
        self.badge.queue_draw();
        self.badge.set_visible(count>1);
        self.button.set_has_tooltip(false);
        *self.members.borrow_mut() = members;
        if let Some(hover) = self.hover.borrow().as_ref() { hover.refresh(); }
    }

    #[cfg(test)]
    pub(crate) fn pin_test_state(&self) -> (Vec<u64>,u64,bool) {
        (self.members.borrow().iter().map(|m|m.0).collect(),self.recent_window.get(),self.dots.get())
    }

    pub fn set_dots(&self, dots: bool) {
        if self.dots.get() == dots && self.badge.is_visible() == (dots || self.count.get()>1) { return; }
        self.dots.set(dots);
        self.badge.set_visible(dots || self.count.get()>1);
        self.badge.queue_draw();
    }

    /// Sets whether the window represented by this button is currently focused.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_focus(&self, focus: bool) {
        let context = self.button.style_context();
        if context.has_class("focused") != focus {
            if focus { context.add_class("focused"); }
            else { context.remove_class("focused"); }
        }
        if focus && context.has_class("urgent") {
            context.remove_class("urgent");
        }
    }

    /// Sets the window title.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_title(&self, title: Option<&str>) {
        let title = title.unwrap_or_default();
        if self.styled_title.borrow().as_deref() == Some(title) { return; }
        *self.styled_title.borrow_mut() = Some(title.to_owned());

        // Apply any app styling rules.
        if let Some(app_id) = &self.app_id {
                let config = self.state.config();
                let context = self.button.style_context();
                let matching: Vec<_> = config.app_matches(app_id, title).collect();
                for class in config.app_classes(app_id) {
                    let wanted = matching.contains(&class);
                    if context.has_class(class) != wanted {
                        if wanted { context.add_class(class); }
                        else { context.remove_class(class); }
                    }
                }
        }
    }

    /// Sets the window to urgent: that is, needing attention.
    ///
    /// This state is automatically cleared the next time the window is focused.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_urgent(&self) {
        self.button.style_context().add_class("urgent");
    }

    /// Returns the actual [`gtk::Button`] widget.
    pub fn widget(&self) -> &gtk::Button {
        &self.button
    }

    fn connect_click_handler(&self, _window_id: u64) {
        let state = self.state.clone();
        let app_id = self.app_id.clone();
        let activate: Rc<dyn Fn(u64)> = Rc::new(move |id| {
            if id == 0 {
                if let Some(app) = &app_id { crate::panel::launch_application(app, false); }
            } else {
                state.niri().activate_window_background(id);
            }
        });
        let pressed = Rc::new(std::cell::Cell::new(None::<u64>));
        let target = self.recent_window.clone();
        let pending = pressed.clone();
        let hover = self.hover.clone();
        self.button.add_events(gtk::gdk::EventMask::BUTTON_PRESS_MASK | gtk::gdk::EventMask::BUTTON_RELEASE_MASK);
        self.button.connect_button_press_event(move |_, event| {
            if event.button() != 1 { return gtk::glib::Propagation::Proceed; }
            // Capture MRU now; a workspace update between press/release must
            // not retarget this click. Cancel even a preview on another card.
            pending.set(Some(target.get()));
            crate::hover::HoverPreview::dismiss_active();
            if let Some(hover) = hover.borrow().as_ref() { hover.dismiss(); }
            gtk::glib::Propagation::Stop
        });
        let pending = pressed.clone();
        let run = activate.clone();
        let hover = self.hover.clone();
        self.button.connect_button_release_event(move |button, event| {
            if event.button() != 1 { return gtk::glib::Propagation::Proceed; }
            let Some(id) = pending.take() else { return gtk::glib::Propagation::Stop; };
            if let Some(hover) = hover.borrow().as_ref() { hover.dismiss(); }
            let (x, y) = event.position();
            if x >= 0. && y >= 0. && x < button.allocated_width() as f64 && y < button.allocated_height() as f64 {
                // Finish the Wayland pointer release before sending FocusWindow;
                // sending it during an implicit pointer grab can eat the first click.
                let run = run.clone();
                gtk::glib::idle_add_local_once(move || run(id));
            }
            gtk::glib::Propagation::Stop
        });
        self.button.connect_unmap(move |_| { pressed.set(None); });
        let target = self.recent_window.clone();
        let hover = self.hover.clone();
        // Pointer signals are consumed above; keep keyboard activation separate.
        self.button.connect_clicked(move |_| {
            crate::hover::HoverPreview::dismiss_active();
            if let Some(hover) = hover.borrow().as_ref() { hover.dismiss(); }
            activate(target.get());
        });
    }

    fn connect_hover_description(&self) {
        // A native popup outside the layer surface avoids clipped bottom-edge tooltips.
        let popup = gtk::Popover::new(Some(&self.button));
        self.hover_popup.replace(Some(popup.clone()));
        popup.set_modal(false);
        popup.set_position(match self.state.config().position() {
            "top"=>gtk::PositionType::Bottom,"left"=>gtk::PositionType::Right,
            "right"=>gtk::PositionType::Left,_=>gtk::PositionType::Top,
        });
        popup.set_constrain_to(gtk::PopoverConstraint::None);
        self.hover.replace(Some(crate::hover::HoverPreview::new(
            &self.button, &popup, self.state.clone(), self.members.clone())));
    }

    /// Opens a small context menu on right click (focus / minimize / close).
    fn connect_context_menu(&self, _window_id: u64) {
        let state = self.state.clone();

        let members = self.members.clone();
        let hover=self.hover.clone();
        let app_id = self.app_id.clone();
        let recent = self.recent_window.clone();
        self.button.connect_button_press_event(move |button, event| {
            if event.button() != 3 {
                return gtk::glib::Propagation::Proceed;
            }

            if let Some(hover)=hover.borrow().as_ref(){hover.dismiss();}
            let terminate = Rc::new(std::cell::Cell::new(state.config().termination_mode() == "shift" && (event.state().contains(gtk::gdk::ModifierType::SHIFT_MASK) || shift_down(&button.display()))));
            let close_items = Rc::new(RefCell::new(Vec::<gtk::glib::WeakRef<gtk::MenuItem>>::new()));
            let close_label = if terminate.get() { crate::i18n::text("结束进程", "End process") } else { crate::i18n::text("关闭窗口", "Close window") };
            let window_id = recent.get();
            tracing::info!(id = window_id, "{}", crate::i18n::text("打开窗口右键菜单", "Open window context menu"));
            let menu = gtk::Menu::new();
            for (label, administrator) in [
                (crate::i18n::text("打开新窗口", "Open new window"), false),
                (crate::i18n::text("以管理员权限运行", "Run as administrator"), true),
            ] {
                let item = gtk::MenuItem::with_label(label);
                item.set_sensitive(app_id.as_ref().is_some_and(|id| !id.is_empty()));
                let app_id = app_id.clone();
                item.connect_activate(move |_| {
                    if let Some(id) = &app_id {
                        crate::panel::launch_application(id, administrator);
                    }
                });
                menu.append(&item);
            }
            if let Some(app) = &app_id {
                let pinned=crate::pins::is_pinned(app);
                let pin=gtk::MenuItem::with_label(if pinned {crate::i18n::text("取消固定", "Unpin from taskbar")} else {crate::i18n::text("固定到任务栏", "Pin to taskbar")});
                let app=app.clone();
                pin.connect_activate(move |_|crate::panel::pin_application(&app,!pinned));
                menu.append(&pin);
            }
            if members.borrow().is_empty() {
                show_menu(menu, event, button);
                return gtk::glib::Propagation::Stop;
            }
            menu.append(&gtk::SeparatorMenuItem::new());
            if members.borrow().len() > 1 {
                for (id,title) in members.borrow().iter() {
                    let item = gtk::MenuItem::with_label(title);
                    let submenu = gtk::Menu::new();
                    for (caption, action) in [(crate::i18n::text("聚焦窗口", "Focus window"),0),
                        (crate::i18n::text("最小化 / 还原", "Minimize / restore"),1),
                        (close_label,2)] {
                        let action_item = gtk::MenuItem::with_label(caption);
                        if action == 2 && state.config().termination_mode() == "shift" {
                            prepare_close(&action_item, &state, terminate.get());
                            close_items.borrow_mut().push(action_item.downgrade());
                        }
                        let terminate = terminate.clone();
                        let state = state.clone(); let id = *id;
                        action_item.connect_activate(move |_| {
                            if action == 2 && terminate.get() { state.niri().terminate_window(id); return; }
                            let result = match action {0 => state.niri().activate_window(id),1=>state.niri().toggle_window_minimized(id),_=>state.niri().close_window(id)};
                            if let Err(error) = result {tracing::warn!(%error,id,"group window action failed");}
                        });
                        submenu.append(&action_item);
                    }
                    if state.config().termination_mode() == "below" { append_terminate(&submenu, &state, *id); }
                    item.set_submenu(Some(&submenu)); menu.append(&item);
                }
                if state.config().termination_mode() == "shift" {
                    track_shift(&menu, terminate, close_items);
                }
                show_menu(menu, event, button);
                return gtk::glib::Propagation::Stop;
            }
            let focus = gtk::MenuItem::with_label(crate::i18n::text("聚焦窗口", "Focus window"));
            let minimize = gtk::MenuItem::with_label(crate::i18n::text("最小化 / 还原", "Minimize / restore"));
            let close = gtk::MenuItem::with_label(close_label);
            if state.config().termination_mode() == "shift" {
                prepare_close(&close, &state, terminate.get());
                close_items.borrow_mut().push(close.downgrade());
            }

            let clicked_state = state.clone();
            focus.connect_activate(move |_| {
                if let Err(e) = clicked_state.niri().activate_window(window_id) {
                    tracing::warn!(%e, id = window_id, "error trying to activate window");
                }
            });

            let clicked_state = state.clone();
            minimize.connect_activate(move |_| {
                if let Err(e) = clicked_state.niri().toggle_window_minimized(window_id) {
                    tracing::warn!(%e, id = window_id, "error toggling window minimize state");
                }
            });

            let clicked_state = state.clone();
            let close_terminate = terminate.clone();
            close.connect_activate(move |_| {
                if close_terminate.get() { clicked_state.niri().terminate_window(window_id); return; }
                if let Err(e) = clicked_state.niri().close_window(window_id) {
                    tracing::warn!(%e, id = window_id, "error trying to close window");
                }
            });

            menu.append(&focus);
            menu.append(&minimize);
            menu.append(&close);
            if state.config().termination_mode() == "below" { append_terminate(&menu, &state, window_id); }
            if state.config().termination_mode() == "shift" {
                track_shift(&menu, terminate, close_items);
            }
            show_menu(menu, event, button);

            gtk::glib::Propagation::Stop
        });
    }

    #[tracing::instrument(level = "TRACE")]
    fn connect_size_allocate(&self) {
        let last_size = Rc::new(RefCell::new(None));
        let icon_path = Rc::new(RefCell::new(None::<PathBuf>));
        if let Some(id) = self.app_id.clone() {
            let cache = self.state.icon_cache().clone();
            let path = icon_path.clone();
            let last = last_size.clone();
            let weak = self.button.downgrade();
            gtk::glib::spawn_future_local(async move {
                let Ok(found) = gtk::gio::spawn_blocking(move || cache.lookup(&id)).await else { return; };
                if let Some(button) = weak.upgrade() {
                    if button.in_destruction() { return; }
                    *path.borrow_mut() = found;
                    last.borrow_mut().take();
                    button.queue_resize();
                }
            });
        }
        let icon = self.icon.clone();
        let vertical = self.state.config().vertical();
        let lane = (self.state.config().thickness() / self.state.config().rows()) as i32;

        self.button
            .connect_size_allocate(move |button, allocation| {
                // Lyrics animate along the bar's long axis. That allocation
                // change cannot change an icon's pixel size, and decoding on
                // every animation frame synchronously stalls the GTK thread.
                // DPI and the cross axis do affect the image; an async path
                // lookup also invalidates this key above.
                let cross = if vertical { allocation.width() } else { allocation.height() };
                let key = (cross.min(lane), button.scale_factor());
                let must_redraw = last_size.replace(Some(key)) != Some(key)
                    || icon.child().is_none();

                if must_redraw {
                    // Calculate the actual image size we need.
                    //
                    // Gtk3 doesn't provide a useful way to get the actual inner size of the
                    // element after applying style rules, so we have to do that here, otherwise we
                    // may draw the image too big and cause the container to grow. (Which will then
                    // result in another size allocate signal, which will result in another
                    // recalculation, which then results in your taskbar taking up your entire
                    // display within a few seconds.)
                    //
                    // Blindly using StateFlags::NORMAL probably isn't actually the right
                    // behaviour, but it's the best we've got for now.
                    //
                    // Note that we have to do this _after_ we figure out if we need to redraw:
                    // calculating the style information is apparently expensive enough that Gtk
                    // essentially busy-waits, which (a) burns CPU, and (b) means that :hover
                    // styles don't get applied. What that means in practice is that, if waybar's
                    // dynamically reloading CSS feature is enabled, sizing changes won't be
                    // applied after the button is first rendered.
                    //
                    // That seems to be the price we have to pay, though, so here we are.
                    let context = button.style_context();
                    let border = context.border(StateFlags::NORMAL);
                    let margin = context.margin(StateFlags::NORMAL);
                    let padding = context.padding(StateFlags::NORMAL);

                    let (available, decoration) = if vertical {
                        (allocation.width(), border.horizontal_size()+margin.horizontal_size()+padding.horizontal_size())
                    } else {
                        (allocation.height(), border.vertical_size()+margin.vertical_size()+padding.vertical_size())
                    };
                    let size = (available.min(lane) - decoration).max(1);

                    // Now we know the size, we can actually load the image.
                    let image =
                        Self::icon_image(icon_path.borrow().as_ref(), button, size).unwrap_or_else(|| {
                            // If we can't find an application icon, then we need to use a
                            // fallback.
                            static FALLBACK_ICON: &str = "application-x-executable";

                            // We'll try to look the icon up in the default icon theme, since then
                            // we can load up the actual image and control its scaling and display.
                            ICON_THEME
                                .with(|theme| {
                                    theme.lookup_icon_for_scale(
                                        FALLBACK_ICON,
                                        size,
                                        button.scale_factor(),
                                        IconLookupFlags::empty(),
                                    )
                                })
                                .and_then(|info| {
                                    Self::icon_image(info.filename().as_ref(), button, size)
                                })
                                .unwrap_or_else(|| {
                                    // But, if all else fails, we'll just use the default button
                                    // size and YOLO it.
                                    gtk::Image::from_icon_name(
                                        Some(FALLBACK_ICON),
                                        IconSize::Button,
                                    )
                                })
                        });

                    // Finally, we can set the button image. Doing this from the callback doesn't
                    // seem to work reliably for reasons I don't understand at all, but doing it
                    // from the main loop as soon as possible does. :shrug:
                    let icon = icon.clone();
                    gtk::glib::source::idle_add_local_once(move || {
                        if let Some(old) = icon.child() { icon.remove(&old); }
                        icon.add(&image);
                        image.show();
                    });
                }
            });
    }

    fn icon_image(
        icon_path: Option<&PathBuf>,
        button: &gtk::Button,
        size: i32,
    ) -> Option<gtk::Image> {
        let size = size * button.scale_factor();

        icon_path
            .and_then(
                |path| match Pixbuf::from_file_at_scale(path, size, size, true) {
                    Ok(pixbuf) => Some(pixbuf),
                    Err(e) => {
                        tracing::info!(%e, ?path, "cannot load icon");
                        None
                    }
                },
            )
            .and_then(|pixbuf| pixbuf.create_surface(0, button.window().as_ref()))
            .map(|surface| gtk::Image::from_surface(Some(&surface)))
    }
}

trait BorderExt {
    fn vertical_size(&self) -> i32;
    fn horizontal_size(&self) -> i32;
}

impl BorderExt for Border {
    fn horizontal_size(&self) -> i32 { (self.left + self.right).into() }
    fn vertical_size(&self) -> i32 {
        (self.top + self.bottom).into()
    }
}

fn prepare_close(item: &gtk::MenuItem, state: &State, terminate: bool) {
    crate::menu_style::destructive(item, state.config().window_animations(), state.config().animation_duration());
    if !terminate { item.style_context().remove_class("adws-destructive"); }
}

fn shift_down(display: &gtk::gdk::Display) -> bool {
    gtk::gdk::Keymap::for_display(display).is_some_and(|keys|
        keys.modifier_state() & gtk::gdk::ModifierType::SHIFT_MASK.bits() != 0)
}

// A layer surface can receive a pointer event before the compositor supplies
// keyboard focus/modifiers for the popup. Seed from the keymap as well as the
// click, then track both root and grouped menus without a polling timer.
fn track_shift(menu: &gtk::Menu, terminate: Rc<std::cell::Cell<bool>>,
               items: Rc<RefCell<Vec<gtk::glib::WeakRef<gtk::MenuItem>>>>) {
    let held = Rc::new(std::cell::Cell::new((false, false)));
    let update: Rc<dyn Fn(bool)> = Rc::new(move |active| {
        terminate.set(active);
        for item in items.borrow().iter().filter_map(|item| item.upgrade()) {
            item.set_label(if active {crate::i18n::text("结束进程", "End process")} else {crate::i18n::text("关闭窗口", "Close window")});
            if active {item.style_context().add_class("adws-destructive");}
            else {item.style_context().remove_class("adws-destructive");}
        }
    });
    if let Some(keymap) = gtk::gdk::Keymap::for_display(&menu.display()) {
        let apply = update.clone();
        let held_keys = held.clone();
        let handler = keymap.connect_state_changed(move |keys| {
            let active = keys.modifier_state() & gtk::gdk::ModifierType::SHIFT_MASK.bits() != 0;
            if !active { held_keys.set((false, false)); }
            apply(active);
        });
        let connection = Rc::new(RefCell::new(Some(handler)));
        let keys = keymap.clone();
        let id = connection.clone();
        menu.connect_deactivate(move |_| {if let Some(id)=id.borrow_mut().take(){keys.disconnect(id);}});
        menu.connect_destroy(move |_| {if let Some(id)=connection.borrow_mut().take(){keymap.disconnect(id);}});
    }
    bind_shift_events(menu, update, held);
}

fn bind_shift_events(menu: &gtk::Menu, update: Rc<dyn Fn(bool)>,
                     held: Rc<std::cell::Cell<(bool, bool)>>) {
    let apply = update.clone();
    menu.connect_map(move |menu| {
        // Do not erase a valid click mask with a stale, unfocused Wayland
        // keymap. Subsequent state-changed/pointer events are authoritative.
        if shift_down(&menu.display()) { apply(true); }
    });
    let apply = update.clone();
    let pressed = held.clone();
    menu.connect_key_press_event(move |_, event| {
        let (mut left, mut right) = pressed.get();
        match event.keyval() {
            gtk::gdk::keys::constants::Shift_L => left = true,
            gtk::gdk::keys::constants::Shift_R => right = true,
            _ => { apply(event.state().contains(gtk::gdk::ModifierType::SHIFT_MASK)); return gtk::glib::Propagation::Proceed; }
        }
        pressed.set((left, right));
        apply(true);
        gtk::glib::Propagation::Proceed
    });
    let apply = update.clone();
    let released = held.clone();
    menu.connect_key_release_event(move |menu, event| {
        let (mut left, mut right) = released.get();
        match event.keyval() {
            gtk::gdk::keys::constants::Shift_L => left = false,
            gtk::gdk::keys::constants::Shift_R => right = false,
            _ => return gtk::glib::Propagation::Proceed,
        }
        released.set((left, right));
        apply(if menu.display().type_().name() == "GdkWaylandDisplay" {
            shift_down(&menu.display()) || left || right
        } else { left || right });
        gtk::glib::Propagation::Proceed
    });
    for child in menu.children() {
        if let Ok(item) = child.downcast::<gtk::MenuItem>() {
            let apply = update.clone();
            let held_keys = held.clone();
            item.connect_enter_notify_event(move |item, event| {
                let (left, right) = held_keys.get();
                // A crossing event may have been queued before the popup gained
                // keyboard focus; do not replace current modifiers with that zero.
                apply(event.state().contains(gtk::gdk::ModifierType::SHIFT_MASK)
                    || shift_down(&item.display()) || left || right);
                gtk::glib::Propagation::Proceed
            });
            if let Some(submenu) = item.submenu().and_then(|w| w.downcast::<gtk::Menu>().ok()) {
                bind_shift_events(&submenu, update.clone(), held.clone());
            }
        }
    }
}

fn append_terminate(menu: &gtk::Menu, state: &crate::state::State, id: u64) {
    let item=gtk::MenuItem::with_label(crate::i18n::text("结束进程", "End process"));
    crate::menu_style::destructive(&item,state.config().window_animations(),state.config().animation_duration());
    item.set_tooltip_text(Some(crate::i18n::text("强制终止所属进程，未保存的内容会丢失。", "Force-terminate the owning process. Unsaved work will be lost.")));
    let niri=*state.niri();
    item.connect_activate(move |_| niri.terminate_window(id));
    menu.append(&item);
}

// Wayland does not send modifiers to a keyboard-inert layer surface. Merely
// reading GDK state cannot recover a Shift held in another application's focus.
// Temporarily allow focus while the popup is active, then restore the bar's mode.
// Resolve the runtime library dynamically: non-layer/X11 hosts need no new link.
#[derive(Clone, Copy)]
struct LayerKeyboardApi {
    is_layer: unsafe extern "C" fn(*mut gtk::ffi::GtkWindow) -> i32,
    get_mode: unsafe extern "C" fn(*mut gtk::ffi::GtkWindow) -> i32,
    set_mode: unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32),
}
#[link(name = "dl")]
unsafe extern "C" {
    fn dlopen(name: *const std::ffi::c_char, flags: i32) -> *mut std::ffi::c_void;
    fn dlsym(handle: *mut std::ffi::c_void, name: *const std::ffi::c_char) -> *mut std::ffi::c_void;
}
fn layer_keyboard_api() -> Option<LayerKeyboardApi> {
    static API: std::sync::OnceLock<Option<LayerKeyboardApi>> = std::sync::OnceLock::new();
    *API.get_or_init(|| unsafe {
        // The cached function pointers keep this single handle alive for the process.
        let handle = dlopen(c"libgtk-layer-shell.so.0".as_ptr(), 1);
        if handle.is_null() { return None; }
        let is_layer = dlsym(handle, c"gtk_layer_is_layer_window".as_ptr());
        let get_mode = dlsym(handle, c"gtk_layer_get_keyboard_mode".as_ptr());
        let set_mode = dlsym(handle, c"gtk_layer_set_keyboard_mode".as_ptr());
        if is_layer.is_null() || get_mode.is_null() || set_mode.is_null() { return None; }
        Some(LayerKeyboardApi {
            is_layer: std::mem::transmute::<*mut std::ffi::c_void, unsafe extern "C" fn(*mut gtk::ffi::GtkWindow) -> i32>(is_layer),
            get_mode: std::mem::transmute::<*mut std::ffi::c_void, unsafe extern "C" fn(*mut gtk::ffi::GtkWindow) -> i32>(get_mode),
            set_mode: std::mem::transmute::<*mut std::ffi::c_void, unsafe extern "C" fn(*mut gtk::ffi::GtkWindow, i32)>(set_mode),
        })
    })
}
fn menu_keyboard_focus(menu: &gtk::Menu, button: &gtk::Button) {
    use gtk::glib::translate::ToGlibPtr;
    let Some(api) = layer_keyboard_api() else { return; };
    let Some(window) = button.toplevel().and_then(|w| w.downcast::<gtk::Window>().ok()) else { return; };
    // SAFETY: all calls are on GTK's owning thread, with a live GtkWindow.
    let previous = unsafe {
        if (api.is_layer)(window.to_glib_none().0) == 0 { return; }
        let mode = (api.get_mode)(window.to_glib_none().0);
        if mode != 0 { return; } // Preserve an existing interactive mode.
        (api.set_mode)(window.to_glib_none().0, 2); // GTK_LAYER_SHELL_KEYBOARD_MODE_ON_DEMAND
        mode
    };
    let weak = window.downgrade();
    let restored = Rc::new(std::cell::Cell::new(false));
    let restore: Rc<dyn Fn()> = Rc::new(move || {
        if restored.replace(true) { return; }
        if let Some(window) = weak.upgrade() {
            if !window.in_destruction() {
                unsafe { (api.set_mode)(window.to_glib_none().0, previous); }
            }
        }
    });
    let close = restore.clone();
    menu.connect_deactivate(move |_| close());
    let close = restore.clone();
    menu.connect_unmap(move |_| close());
    menu.connect_destroy(move |_| restore());
}

fn show_menu(menu: gtk::Menu, event: &gtk::gdk::EventButton, button: &gtk::Button) {
    crate::menu_style::apply(&menu);
    menu.show_all();
    menu.connect_deactivate(|menu| {
        ACTIVE_CONTEXT_MENU.with(|slot| {slot.borrow_mut().take();});
        // GTK deactivates the shell BEFORE activating the chosen item.
        // Destroying its children here disconnects the action, including pkexec.
        // Release this popup after activation has completed, not during it.
        let menu=menu.clone();
        gtk::glib::idle_add_local_once(move || unsafe { menu.destroy(); });
    });
    ACTIVE_CONTEXT_MENU.with(|slot| {
        let old = slot.borrow_mut().take();
        if let Some(old) = old {old.popdown(); unsafe { old.destroy(); }}
        *slot.borrow_mut() = Some(menu.clone());
    });
    menu_keyboard_focus(&menu, button);
    menu.popup_at_pointer(Some(event));
}

impl Drop for Button {
    fn drop(&mut self) { self.hover.borrow_mut().take(); }
}

#[cfg(test)]
mod action_tests {
    use super::*;
    use gtk::glib::translate::{IntoGlib, ToGlibPtr};
    fn settle() {
        for _ in 0..20 { while gtk::events_pending(){gtk::main_iteration();} std::thread::sleep(std::time::Duration::from_millis(5)); }
    }
    #[test]
    #[ignore = "requires nested Wayland compositor and external real-input driver"]
    fn wayland_layer_shift_menu() {
        use gtk::glib::translate::ToGlibPtr;
        use std::time::{Duration,Instant};
        #[link(name = "gtk-layer-shell")]
        unsafe extern "C" {
            fn gtk_layer_init_for_window(window: *mut gtk::ffi::GtkWindow);
            fn gtk_layer_set_layer(window: *mut gtk::ffi::GtkWindow, layer: i32);
            fn gtk_layer_set_anchor(window: *mut gtk::ffi::GtkWindow, edge: i32, anchor: i32);
            fn gtk_layer_set_exclusive_zone(window: *mut gtk::ffi::GtkWindow, zone: i32);
        }
        gtk::init().unwrap();
        assert_eq!(gtk::gdk::Display::default().unwrap().type_().name(),"GdkWaylandDisplay");
        let folder=PathBuf::from(std::env::var_os("ADWS_SHIFT_TEST_DIR").unwrap());
        let api=layer_keyboard_api().unwrap();
        let window=gtk::Window::new(gtk::WindowType::Toplevel);
        unsafe {
            gtk_layer_init_for_window(window.to_glib_none().0);
            gtk_layer_set_layer(window.to_glib_none().0,1);
            for edge in [0,1,3] {gtk_layer_set_anchor(window.to_glib_none().0,edge,1);}
            gtk_layer_set_exclusive_zone(window.to_glib_none().0,60);
            (api.set_mode)(window.to_glib_none().0,0);
        }
        window.set_size_request(-1,60);
        let state=State::new(serde_json::from_value(serde_json::json!({"termination_mode":"shift"})).unwrap());
        let single=Button::create(&state,Some("adws-test".into()),101,"Single".into());
        let spacer=gtk::Label::new(None);
        // Keep hover previews out of this input/focus regression.
        single.hover.borrow_mut().take();
        let row=gtk::Box::new(gtk::Orientation::Horizontal,0);
        row.pack_start(single.widget(),true,true,0);row.pack_start(&spacer,true,true,0);
        window.add(&row);window.show_all();settle();
        let a=single.widget().allocation();
        std::fs::write(folder.join("ready.json"),serde_json::json!({"single":[a.x()+a.width()/2,a.y()+a.height()/2],"height":window.allocated_height()}).to_string()).unwrap();
        fn labels(menu:&gtk::Menu,grouped:bool,active:bool)->bool {
            let wanted=if active{crate::i18n::text("结束进程","End process")}else{crate::i18n::text("关闭窗口","Close window")};
            let menus:Vec<gtk::Menu>=if grouped{menu.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).filter_map(|i|i.submenu()).filter_map(|s|s.downcast::<gtk::Menu>().ok()).collect()}else{vec![menu.clone()]};
            !menus.is_empty() && menus.iter().all(|m|m.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).any(|i|i.label().as_deref()==Some(wanted) && i.style_context().has_class("adws-destructive")==active))
        }
        let wait=|predicate:&dyn Fn()->bool| {
            let until=Instant::now()+Duration::from_secs(8);
            while !predicate() {
                if Instant::now()>=until {
                    eprintln!("mode={} single={:?}",unsafe{(api.get_mode)(window.to_glib_none().0)},single.widget().allocation());
                    ACTIVE_CONTEXT_MENU.with(|m|eprintln!("menu={:?}",m.borrow().as_ref().map(|m|m.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).map(|i|i.label()).collect::<Vec<_>>())));
                    panic!("timed out waiting for real Wayland input");
                }
                while gtk::events_pending(){gtk::main_iteration();}
                std::thread::sleep(Duration::from_millis(5));
            }
        };
        let grouped=false;
        let prefix="single";
        for (suffix,active) in [("shift",true),("close",false),("repress",true),("restored",false)] {
            let phase=format!("{prefix}-{suffix}");
            if phase.ends_with("restored") {
                wait(&||ACTIVE_CONTEXT_MENU.with(|m|m.borrow().is_none()) && unsafe{(api.get_mode)(window.to_glib_none().0)}==0);
            } else {
                wait(&||ACTIVE_CONTEXT_MENU.with(|m|m.borrow().as_ref().is_some_and(|m|labels(m,grouped,active))) && unsafe{(api.get_mode)(window.to_glib_none().0)}==2);
            }
            std::fs::write(folder.join("phase"),phase).unwrap();
        }
        unsafe {window.destroy();}
    }

    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn context_menu_shell_preserves_selected_action() {
        gtk::init().unwrap();
        let window=gtk::Window::new(gtk::WindowType::Toplevel);
        let button=gtk::Button::with_label("Fixture");
        window.add(&button);window.show_all();settle();
        let mut event=gtk::gdk::Event::new(gtk::gdk::EventType::ButtonPress).downcast::<gtk::gdk::EventButton>().unwrap();
        event.as_mut().window=button.window().unwrap().to_glib_full();event.as_mut().button=3;
        event.set_device(window.display().default_seat().unwrap().pointer().as_ref());
        for grouped in [false,true] {
            let menu=gtk::Menu::new();
            let target=if grouped {
                let submenu=gtk::Menu::new();
                let parent=gtk::MenuItem::with_label("Group");
                parent.set_submenu(Some(&submenu));menu.append(&parent);submenu
            } else {menu.clone()};
            let item=gtk::MenuItem::with_label("Administrator fixture");
            let calls=Rc::new(std::cell::Cell::new(0));let count=calls.clone();
            item.connect_activate(move |_|count.set(count.get()+1));target.append(&item);
            show_menu(menu.clone(),&event,&button);settle();
            if grouped {
                let parent=menu.children()[0].clone().downcast::<gtk::MenuItem>().unwrap();
                menu.select_item(&parent);
                for _ in 0..6 {settle();}
                assert!(target.is_mapped(),"submenu must be open before shell activation");
            }
            let weak=menu.downgrade();
            // This is GTK's actual click/Enter path, not MenuItem::activate().
            target.activate_item(&item,true);
            assert_eq!(calls.get(),1,"deactivation must not disconnect the action");
            assert!(ACTIVE_CONTEXT_MENU.with(|slot|slot.borrow().is_none()));
            drop(item);drop(target);drop(menu);settle();
            assert!(weak.upgrade().is_none(),"dismissed menu must still be released");
        }
        unsafe{window.destroy();}
    }

    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn termination_modes_and_submenu_styles() {
        gtk::init().unwrap();
        for mode in ["shift","below","disabled"] {
            for shift in [false,true] {
                for grouped in [false,true] {
                    let config=serde_json::from_value(serde_json::json!({"termination_mode":mode,"window_animations":false})).unwrap();
                    let state=crate::state::State::new(config);
                    let button=Button::create(&state,Some("adws-test".into()),101,"Test window".into());
                    if grouped {button.set_group(vec![(101,"One".into()),(102,"Two".into())],101);}
                    let window=gtk::Window::new(gtk::WindowType::Toplevel);
                    window.add(button.widget());window.show_all();settle();
                    let mut event=gtk::gdk::Event::new(gtk::gdk::EventType::ButtonPress).downcast::<gtk::gdk::EventButton>().unwrap();
                    event.as_mut().window=button.widget().window().unwrap().to_glib_full();
                    event.as_mut().button=3;
                    event.as_mut().state=if shift {gtk::gdk::ModifierType::SHIFT_MASK.bits()}else{0};
                    event.set_device(gtk::gdk::Display::default().unwrap().default_seat().unwrap().pointer().as_ref());
                    assert!(button.widget().emit_by_name::<bool>("button-press-event", &[&*event]));settle();
                    let menu=ACTIVE_CONTEXT_MENU.with(|m|m.borrow().clone()).unwrap();
                    let target=if grouped { menu.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).find_map(|i|i.submenu()).unwrap().downcast::<gtk::Menu>().unwrap() } else {menu.clone()};
                    assert!(target.style_context().has_class("adws-menu"));
                    let labels:Vec<_>=target.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).filter_map(|i|i.label()).map(|s|s.to_string()).collect();
                    let kill=crate::i18n::text("结束进程","End process");let close=crate::i18n::text("关闭窗口","Close window");
                    let replacing=mode=="shift"&&shift;
                    assert_eq!(labels.iter().any(|s|s==kill),mode=="below"||replacing,"mode={mode} shift={shift}");
                    assert_eq!(labels.iter().any(|s|s==close),!replacing);
                    if mode=="below" {assert_eq!(labels.last().unwrap(),kill);}
                    // Modifiers can arrive after a Wayland popup takes its grab.
                    if mode=="shift" {
                        // Keyboard focus can be on a grouped submenu, not the root.
                        for receiver in [&menu, &target] {
                            for held in [true,false,true] {
                                let mut key=gtk::gdk::Event::new(if held {gtk::gdk::EventType::KeyPress}else{gtk::gdk::EventType::KeyRelease}).downcast::<gtk::gdk::EventKey>().unwrap();
                                key.as_mut().keyval=gtk::gdk::keys::constants::Shift_L.into_glib();
                                receiver.emit_by_name::<bool>(if held {"key-press-event"}else{"key-release-event"}, &[&*key]);
                                let close_item=target.children().into_iter().filter_map(|w|w.downcast::<gtk::MenuItem>().ok()).find(|item|item.label().as_deref()==Some(if held{kill}else{close})).unwrap();
                                assert_eq!(close_item.style_context().has_class("adws-destructive"),held);
                            }
                        }
                        // Releasing one of two held Shift keys must retain termination.
                        for (keyval, pressed, expected) in [
                            (gtk::gdk::keys::constants::Shift_R,true,true),
                            (gtk::gdk::keys::constants::Shift_L,false,true),
                            (gtk::gdk::keys::constants::Shift_R,false,false),
                        ] {
                            let mut key=gtk::gdk::Event::new(if pressed {gtk::gdk::EventType::KeyPress}else{gtk::gdk::EventType::KeyRelease}).downcast::<gtk::gdk::EventKey>().unwrap();
                            key.as_mut().keyval=keyval.into_glib();
                            target.emit_by_name::<bool>(if pressed {"key-press-event"}else{"key-release-event"}, &[&*key]);
                            assert!(target.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).any(|i|i.label().as_deref()==Some(if expected{kill}else{close})));
                        }
                    }
                    menu.popdown();settle();
                    unsafe{window.destroy();}
                }
            }
        }
        // XTest changes the actual keymap, while the initiating pointer event
        // deliberately carries no Shift bit (the Wayland focus handoff case).
        let window=gtk::Window::new(gtk::WindowType::Toplevel);
        let state=State::new(serde_json::from_value(serde_json::json!({"termination_mode":"shift"})).unwrap());
        let button=Button::create(&state,Some("adws-test".into()),101,"Test window".into());
        window.add(button.widget());window.show_all();settle();
        assert!(std::process::Command::new("xdotool").args(["keydown","Shift_L"]).status().unwrap().success());
        settle();
        assert!(shift_down(&window.display()));
        let mut event=gtk::gdk::Event::new(gtk::gdk::EventType::ButtonPress).downcast::<gtk::gdk::EventButton>().unwrap();
        event.as_mut().window=button.widget().window().unwrap().to_glib_full();
        event.as_mut().button=3;
        event.as_mut().state=0;
        event.set_device(window.display().default_seat().unwrap().pointer().as_ref());
        button.widget().emit_by_name::<bool>("button-press-event", &[&*event]);settle();
        let menu=ACTIVE_CONTEXT_MENU.with(|m|m.borrow().clone()).unwrap();
        let kill=crate::i18n::text("结束进程","End process");
        assert!(menu.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).any(|i|i.label().as_deref()==Some(kill)));
        assert!(std::process::Command::new("xdotool").args(["keyup","Shift_L"]).status().unwrap().success());
        settle();
        assert!(menu.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).any(|i|i.label().as_deref()==Some(crate::i18n::text("关闭窗口","Close window"))));
        let weak=menu.downgrade();
        menu.popdown();menu.emit_by_name::<()>("deactivate", &[]);drop(menu);settle();
        assert!(weak.upgrade().is_none(),"popup and modifier handlers must be released");
        unsafe{window.destroy();}

    }
    #[test]
    #[ignore = "requires an isolated GTK display and fixture IPC socket"]
    fn termination_action_matches_displayed_label() {
        use std::io::{BufRead, BufReader, Write};
        use std::os::unix::{net::UnixListener, process::ExitStatusExt};
        use std::time::{Duration, Instant};
        struct FixtureChild(std::process::Child);
        impl Drop for FixtureChild {
            fn drop(&mut self) { let _=self.0.kill(); let _=self.0.wait(); }
        }
        struct SocketEnv(Option<std::ffi::OsString>);
        impl Drop for SocketEnv {
            fn drop(&mut self) { unsafe {
                if let Some(old)=self.0.take() {std::env::set_var("NIRI_SOCKET",old);}
                else {std::env::remove_var("NIRI_SOCKET");}
            } }
        }
        gtk::init().unwrap();
        for grouped in [false,true] {
            // Only this disposable test child can be terminated by the fixture.
            let mut child=FixtureChild(std::process::Command::new("sleep").arg("20").spawn().unwrap());
            let pid=child.0.id();
            let path=std::env::temp_dir().join(format!("adws-shift-actions-{}-{grouped}.sock",std::process::id()));
            let listener=UnixListener::bind(&path).unwrap();listener.set_nonblocking(true).unwrap();
            let _env=SocketEnv(std::env::var_os("NIRI_SOCKET"));
            unsafe{std::env::set_var("NIRI_SOCKET",&path);}
            let (tx,rx)=std::sync::mpsc::channel();
            let server=std::thread::spawn(move || {
                let deadline=Instant::now()+Duration::from_secs(5);
                let mut requests=0;
                while requests<2 && Instant::now()<deadline {
                    let (mut stream,_)=match listener.accept() {
                        Ok(pair)=>pair,
                        Err(e) if e.kind()==std::io::ErrorKind::WouldBlock=>{std::thread::sleep(Duration::from_millis(5));continue;}
                        Err(e)=>panic!("{e}"),
                    };
                    stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
                    let mut line=String::new();
                    BufReader::new(stream.try_clone().unwrap()).read_line(&mut line).unwrap();
                    let request:serde_json::Value=serde_json::from_str(&line).unwrap();
                    let reply=if request==serde_json::json!("Windows") {
                        serde_json::json!({"Ok":{"Windows":[{
                            "id":101,"pid":pid,"title":"Fixture","app_id":"adws-test",
                            "workspace_id":1,"is_focused":true,"is_floating":false,"is_urgent":false,"focus_timestamp":null,
                            "layout":{"pos_in_scrolling_layout":[1,1],"tile_size":[100,100],"window_size":[100,100],"tile_pos_in_workspace_view":[0,0],"window_offset_in_tile":[0,0]}
                        }]}})
                    } else {serde_json::json!({"Ok":"Handled"})};
                    writeln!(stream,"{reply}").unwrap();tx.send(request).unwrap();requests+=1;
                }
                assert_eq!(requests,2,"close and terminate should each request IPC once");
            });
            let state=State::new(serde_json::from_value(serde_json::json!({"termination_mode":"shift"})).unwrap());
            let button=Button::create(&state,Some("adws-test".into()),101,"Fixture".into());
            if grouped {button.set_group(vec![(101,"One".into()),(102,"Two".into())],101);}
            let window=gtk::Window::new(gtk::WindowType::Toplevel);
            window.add(button.widget());window.show_all();settle();
            let mut event=gtk::gdk::Event::new(gtk::gdk::EventType::ButtonPress).downcast::<gtk::gdk::EventButton>().unwrap();
            event.as_mut().window=button.widget().window().unwrap().to_glib_full();event.as_mut().button=3;
            event.set_device(window.display().default_seat().unwrap().pointer().as_ref());
            button.widget().emit_by_name::<bool>("button-press-event", &[&*event]);settle();
            let menu=ACTIVE_CONTEXT_MENU.with(|m|m.borrow().clone()).unwrap();
            let target=if grouped {menu.children().iter().filter_map(|w|w.downcast_ref::<gtk::MenuItem>()).find_map(|i|i.submenu()).unwrap().downcast::<gtk::Menu>().unwrap()} else {menu.clone()};
            let close=target.children().into_iter().filter_map(|w|w.downcast::<gtk::MenuItem>().ok()).find(|i|i.label().as_deref()==Some(crate::i18n::text("关闭窗口","Close window"))).unwrap();
            close.activate();
            assert_eq!(rx.recv_timeout(Duration::from_secs(2)).unwrap(),serde_json::json!({"Action":{"CloseWindow":{"id":101}}}));
            assert!(child.0.try_wait().unwrap().is_none(),"normal close must not kill the process");
            let mut key=gtk::gdk::Event::new(gtk::gdk::EventType::KeyPress).downcast::<gtk::gdk::EventKey>().unwrap();
            key.as_mut().keyval=gtk::gdk::keys::constants::Shift_R.into_glib();
            target.emit_by_name::<bool>("key-press-event", &[&*key]);
            assert_eq!(close.label().as_deref(),Some(crate::i18n::text("结束进程","End process")));
            close.activate();
            assert_eq!(rx.recv_timeout(Duration::from_secs(2)).unwrap(),serde_json::json!("Windows"));
            let deadline=Instant::now()+Duration::from_secs(2);
            let status=loop {
                if let Some(status)=child.0.try_wait().unwrap(){break status;}
                assert!(Instant::now()<deadline,"termination did not reach the fixture child");
                std::thread::sleep(Duration::from_millis(5));
            };
            assert_eq!(status.signal(),Some(9));
            server.join().unwrap();std::fs::remove_file(path).unwrap();
            menu.popdown();menu.emit_by_name::<()>("deactivate", &[]);
            unsafe{window.destroy();}settle();
        }
    }

}

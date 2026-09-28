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
        self.dots.set(dots);
        self.badge.set_visible(dots || self.count.get()>1);
        self.badge.queue_draw();
    }

    /// Sets whether the window represented by this button is currently focused.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_focus(&self, focus: bool) {
        let context = self.button.style_context();

        if focus {
            context.add_class("focused");
            context.remove_class("urgent");
        } else {
            context.remove_class("focused");
        }
    }

    /// Sets the window title.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_title(&self, title: Option<&str>) {
        self.button.set_has_tooltip(false);

        // Apply any app styling rules.
        if let Some(app_id) = &self.app_id {
            if let Some(title) = title {
                let config = self.state.config();
                let context = self.button.style_context();

                // First, remove all the possible classes for this app.
                for class in config.app_classes(app_id) {
                    context.remove_class(class);
                }

                // Now add the classes that actually do match.
                for class in config.app_matches(app_id, title) {
                    context.add_class(class);
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
            } else if let Err(error) = state.niri().activate_window(id) {
                tracing::warn!(%error, id, "window activation failed");
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
        self.button.connect_button_press_event(move |_button, event| {
            if event.button() != 3 {
                return gtk::glib::Propagation::Proceed;
            }

            if let Some(hover)=hover.borrow().as_ref(){hover.dismiss();}
            let terminate = Rc::new(std::cell::Cell::new(state.config().termination_mode() == "shift" && event.state().contains(gtk::gdk::ModifierType::SHIFT_MASK)));
            let close_items = Rc::new(RefCell::new(Vec::<gtk::MenuItem>::new()));
            let close_label = if terminate.get() { crate::i18n::text("终止", "Terminate") } else { crate::i18n::text("关闭窗口", "Close window") };
            let window_id = recent.get();
            tracing::info!(id = window_id, "{}", crate::i18n::text("打开窗口右键菜单", "Open window context menu"));
            let menu = gtk::Menu::new();
            if state.config().termination_mode() == "shift" {
                track_shift(&menu, terminate.clone(), close_items.clone());
            }
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
                show_menu(menu, event);
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
                            close_items.borrow_mut().push(action_item.clone());
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
                show_menu(menu, event);
                return gtk::glib::Propagation::Stop;
            }
            let focus = gtk::MenuItem::with_label(crate::i18n::text("聚焦窗口", "Focus window"));
            let minimize = gtk::MenuItem::with_label(crate::i18n::text("最小化 / 还原", "Minimize / restore"));
            let close = gtk::MenuItem::with_label(close_label);
            if state.config().termination_mode() == "shift" {
                prepare_close(&close, &state, terminate.get());
                close_items.borrow_mut().push(close.clone());
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
            close.connect_activate(move |_| {
                if terminate.get() { clicked_state.niri().terminate_window(window_id); return; }
                if let Err(e) = clicked_state.niri().close_window(window_id) {
                    tracing::warn!(%e, id = window_id, "error trying to close window");
                }
            });

            menu.append(&focus);
            menu.append(&minimize);
            menu.append(&close);
            if state.config().termination_mode() == "below" { append_terminate(&menu, &state, window_id); }
            crate::menu_style::apply(&menu);
            menu.show_all();
            menu.connect_deactivate(|_| {
                ACTIVE_CONTEXT_MENU.with(|slot| {
                    slot.borrow_mut().take();
                });
            });

            ACTIVE_CONTEXT_MENU.with(|slot| {
                let old = slot.borrow_mut().take();
                if let Some(old) = old {
                    old.popdown();
                }
                *slot.borrow_mut() = Some(menu.clone());
            });
            // 传入触发事件，让 GTK 在指针位置弹出菜单；不传时部分 Wayland 环境会定位失败。
            menu.popup_at_pointer(Some(event));

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
                // Figure out if we actually need to redraw, since it's relatively expensive.
                //
                // The first condition is pretty easy: is there an image on the button? If not,
                // then it's the first draw, and we have no choice but to draw.
                let mut must_redraw = button.image().is_none();

                // Otherwise, let's check if the size allocation has changed since the last time
                // this was called.
                if !must_redraw {
                    if let Some(last_size) = last_size.take() {
                        if last_size != (allocation.width(), allocation.height()) {
                            must_redraw = true;
                        }
                    } else {
                        must_redraw = true;
                    }

                    last_size.replace(Some((allocation.width(), allocation.height())));
                }

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

// Wayland may deliver keyboard modifiers only after the popup grab. Keep the
// label and the action on the same live state, including grouped submenus.
fn track_shift(menu: &gtk::Menu, terminate: Rc<std::cell::Cell<bool>>, items: Rc<RefCell<Vec<gtk::MenuItem>>>) {
    let update: Rc<dyn Fn(bool)> = Rc::new(move |active| {
        terminate.set(active);
        for item in items.borrow().iter() {
            item.set_label(if active {crate::i18n::text("终止", "Terminate")} else {crate::i18n::text("关闭窗口", "Close window")});
            if active {item.style_context().add_class("adws-destructive");}
            else {item.style_context().remove_class("adws-destructive");}
        }
    });
    if let Some(keymap) = gtk::gdk::Keymap::for_display(&menu.display()) {
        let apply = update.clone();
        let handler = keymap.connect_state_changed(move |keys| {
            apply(keys.modifier_state() & gtk::gdk::ModifierType::SHIFT_MASK.bits() != 0);
        });
        let connection = Rc::new(RefCell::new(Some(handler)));
        let keys = keymap.clone();
        let id = connection.clone();
        menu.connect_deactivate(move |_| {if let Some(id)=id.borrow_mut().take(){keys.disconnect(id);}});
        menu.connect_destroy(move |_| {if let Some(id)=connection.borrow_mut().take(){keymap.disconnect(id);}});
    }
    let apply = update.clone();
    menu.connect_key_press_event(move |_, event| {
        if matches!(event.keyval(), gtk::gdk::keys::constants::Shift_L | gtk::gdk::keys::constants::Shift_R) {apply(true);}
        gtk::glib::Propagation::Proceed
    });
    menu.connect_key_release_event(move |_, event| {
        if matches!(event.keyval(), gtk::gdk::keys::constants::Shift_L | gtk::gdk::keys::constants::Shift_R) {update(false);}
        gtk::glib::Propagation::Proceed
    });
}

fn append_terminate(menu: &gtk::Menu, state: &crate::state::State, id: u64) {
    let item=gtk::MenuItem::with_label(crate::i18n::text("终止", "Terminate"));
    crate::menu_style::destructive(&item,state.config().window_animations(),state.config().animation_duration());
    item.set_tooltip_text(Some(crate::i18n::text("强制终止所属进程，未保存的内容会丢失。", "Force-terminate the owning process. Unsaved work will be lost.")));
    let niri=*state.niri();
    item.connect_activate(move |_| niri.terminate_window(id));
    menu.append(&item);
}

fn show_menu(menu: gtk::Menu, event: &gtk::gdk::EventButton) {
    crate::menu_style::apply(&menu);
    menu.show_all();
    menu.connect_deactivate(|_| { ACTIVE_CONTEXT_MENU.with(|slot| {slot.borrow_mut().take();}); });
    ACTIVE_CONTEXT_MENU.with(|slot| {
        let old = slot.borrow_mut().take();
        if let Some(old) = old {old.popdown();}
        *slot.borrow_mut() = Some(menu.clone());
    });
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
                    let kill=crate::i18n::text("终止","Terminate");let close=crate::i18n::text("关闭窗口","Close window");
                    let replacing=mode=="shift"&&shift;
                    assert_eq!(labels.iter().any(|s|s==kill),mode=="below"||replacing,"mode={mode} shift={shift}");
                    assert_eq!(labels.iter().any(|s|s==close),!replacing);
                    if mode=="below" {assert_eq!(labels.last().unwrap(),kill);}
                    // Modifiers can arrive after a Wayland popup takes its grab.
                    if mode=="shift" {
                        for held in [true,false,true] {
                            let mut key=gtk::gdk::Event::new(if held {gtk::gdk::EventType::KeyPress}else{gtk::gdk::EventType::KeyRelease}).downcast::<gtk::gdk::EventKey>().unwrap();
                            key.as_mut().keyval=gtk::gdk::keys::constants::Shift_L.into_glib();
                            menu.emit_by_name::<bool>(if held {"key-press-event"}else{"key-release-event"}, &[&*key]);
                            let close_item=target.children().into_iter().filter_map(|w|w.downcast::<gtk::MenuItem>().ok()).find(|item|item.label().as_deref()==Some(if held{kill}else{close})).unwrap();
                            assert_eq!(close_item.style_context().has_class("adws-destructive"),held);
                        }
                    }
                    menu.popdown();settle();
                    unsafe{window.destroy();}
                }
            }
        }
    }
}

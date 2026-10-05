//! Run in an isolated display: xvfb-run cargo test --lib -- --ignored.
use super::*;
use gtk::prelude::*;
use serde_json::json;

fn snapshot() -> Snapshot {
    let mut stream = niri::WindowSet::new(false);
    stream.with_event(serde_json::from_value(json!({"WorkspacesChanged":{"workspaces":[{
        "id":10,"idx":1,"name":null,"output":"DP-1","is_urgent":false,
        "is_active":true,"is_focused":true,"active_window_id":2}]}})).unwrap());
    let windows: Vec<_> = ["foot","foot","firefox","code","unknown"].iter().enumerate().map(|(i,app)|json!({
        "id":i+1,"title":format!("Window {}",i+1),"app_id":app,"pid":null,
        "workspace_id":10,"is_focused":i==1,"is_floating":false,"is_urgent":false,
        "focus_timestamp":null,"layout":{"pos_in_scrolling_layout":[1,1],
        "tile_size":[800.0,600.0],"window_size":[800,600],
        "tile_pos_in_workspace_view":[0.0,0.0],"window_offset_in_tile":[0.0,0.0]}
    })).collect();
    stream.with_event(serde_json::from_value(json!({"WindowsChanged":{"windows":windows}})).unwrap()).unwrap()
}

fn settle() {
    for _ in 0..50 {
        while gtk::events_pending() { gtk::main_iteration(); }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
}

#[test]
#[ignore = "requires an isolated GTK display"]
fn panel_geometry_groups_and_colors() {
    gtk::init().unwrap();
    use std::io::{BufRead,BufReader,Write};
    use std::sync::atomic::{AtomicBool,Ordering};
    let socket=std::env::temp_dir().join(format!("adws-press-test-{}.sock",std::process::id()));
    let listener=std::os::unix::net::UnixListener::bind(&socket).unwrap();listener.set_nonblocking(true).unwrap();
    let old_socket=std::env::var_os("NIRI_SOCKET");unsafe{std::env::set_var("NIRI_SOCKET",&socket);}
    let done=Arc::new(AtomicBool::new(false));let done_worker=done.clone();
    let requests=Arc::new(Mutex::new(Vec::new()));let incoming=requests.clone();
    let server=std::thread::spawn(move || {
        while !done_worker.load(Ordering::Relaxed){
            if let Ok((mut stream,_))=listener.accept(){
                stream.set_read_timeout(Some(std::time::Duration::from_secs(1))).unwrap();
                let mut line=String::new();BufReader::new(stream.try_clone().unwrap()).read_line(&mut line).unwrap();
                incoming.lock().unwrap().push(serde_json::from_str::<serde_json::Value>(&line).unwrap());
                writeln!(stream,"{{\"Ok\":\"Handled\"}}").unwrap();
            } else{std::thread::sleep(std::time::Duration::from_millis(5));}
        }
    });
    let base=gtk::CssProvider::new();
    base.load_from_path(concat!(env!("CARGO_MANIFEST_DIR"),"/../../config/waybar/style-bottom.css")).unwrap();
    gtk::StyleContext::add_provider_for_screen(&gtk::gdk::Screen::default().unwrap(),&base,gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    let css=gtk::CssProvider::new();
    css.load_from_data(b".niri-taskbar button {min-width:0; min-height:0; transition:none;} .niri-taskbar button.focused {background:#123456;} .niri-taskbar button:hover:not(.focused) {background:#cc2244;}").unwrap();
    gtk::StyleContext::add_provider_for_screen(&gtk::gdk::Screen::default().unwrap(),&css,gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    for vertical in [false,true] {
        for rows in [1,2] {
            for grouped in [false,true] {
                let config: Config=serde_json::from_value(json!({"vertical":vertical,"rows":rows,"thickness":64,"group_windows":grouped})).unwrap();
                let grid=gtk::Grid::new();
                grid.set_row_homogeneous(!vertical);
                grid.set_column_homogeneous(vertical);
                grid.style_context().add_class("niri-taskbar");
                let window=gtk::Window::new(gtk::WindowType::Toplevel);
                window.add(&grid);
                window.set_default_size(if vertical {64}else{320},if vertical {320}else{64});
                let mut instance=Instance::new(State::new(config),grid.clone());
                let filter=Arc::new(Mutex::new(output::Filter::ShowAll));
                MainContext::default().block_on(instance.process_window_snapshot(snapshot(),filter.clone()));
                window.show_all();settle();
                assert_eq!(grid.children().len(),if grouped{4}else{5});
                let first=instance.buttons[&1].widget();
                assert_eq!(first.style_context().has_class("focused"),grouped);
                if grouped {
                    assert!(!first.has_tooltip());
                    #[allow(deprecated)]
                    let color: gtk::gdk::RGBA=first.style_context().style_property_for_state("background-color",gtk::StateFlags::NORMAL).get().unwrap();
                    assert!((color.red()-18.0/255.0).abs()<0.01,"custom focus color was overridden: {color:?}");
                }
                if grouped && !vertical && rows==1 {
                    let badge=&instance.buttons[&1].badge_test;
                    assert_eq!(badge.allocated_width(),badge.allocated_height());
                    assert!(badge.allocated_width()<=20);
                    let popup=instance.buttons[&1].hover_popup.borrow().clone().unwrap();
                    let enter=gtk::gdk::Event::new(gtk::gdk::EventType::EnterNotify);
                    let _:bool=first.emit_by_name("enter-notify-event",&[&enter]);
                    settle();settle();
                    assert!(popup.is_visible());
                    let content=popup.child().unwrap();
                    for _ in 0..3 {let _:bool=first.emit_by_name("enter-notify-event",&[&enter]);}
                    settle();settle();
                    assert_eq!(popup.child().unwrap(),content,"repeated crossing rebuilt popup");
                    // One complete click focuses MRU after releasing the pointer grab.
                    let mut press=gtk::gdk::Event::new(gtk::gdk::EventType::ButtonPress).downcast::<gtk::gdk::EventButton>().unwrap();
                    press.as_mut().button=1;
                    let mut release=gtk::gdk::Event::new(gtk::gdk::EventType::ButtonRelease).downcast::<gtk::gdk::EventButton>().unwrap();
                    release.as_mut().button=1;
                    assert!(first.emit_by_name::<bool>("button-press-event",&[&*press]));
                    assert!(!popup.is_visible());
                    assert!(requests.lock().unwrap().is_empty(), "focus must wait for release");
                    assert!(first.emit_by_name::<bool>("button-release-event",&[&*release]));
                    settle();
                    let _:bool=first.emit_by_name("enter-notify-event",&[&enter]);settle();settle();
                    fn choices(widget:&gtk::Widget)->Vec<gtk::Button>{
                        if let Ok(button)=widget.clone().downcast::<gtk::Button>(){return if button.style_context().has_class("peek-close"){vec![]}else{vec![button]};}
                        widget.clone().downcast::<gtk::Container>().map(|c|c.children().iter().flat_map(choices).collect()).unwrap_or_default()
                    }
                    let choices=choices(&popup.child().unwrap());assert_eq!(choices.len(),2,"title-only cards must be clickable");
                    choices[0].emit_clicked();settle();
                    assert!(!popup.is_visible());
                    let actions=requests.lock().unwrap();assert_eq!(actions.len(),2);
                    assert_eq!(actions[0]["Action"]["FocusWindow"]["id"],2);
                    assert_eq!(actions[1]["Action"]["FocusWindow"]["id"],1);drop(actions);
                    let _:bool=first.emit_by_name("enter-notify-event",&[&enter]);settle();settle();

                    // A sibling close control sends only CloseWindow, never FocusWindow.
                    fn close_control(widget:&gtk::Widget)->Option<gtk::Button>{
                        if let Some(b)=widget.downcast_ref::<gtk::Button>() {if b.style_context().has_class("peek-close"){return Some(b.clone());}}
                        widget.clone().downcast::<gtk::Container>().ok().and_then(|c|c.children().iter().find_map(close_control))
                    }
                    let before_close=requests.lock().unwrap().len();
                    close_control(&popup.child().unwrap()).unwrap().emit_clicked();settle();
                    assert!(!popup.is_visible());
                    {let actions=requests.lock().unwrap();assert_eq!(actions.len(),before_close+1);assert!(actions.last().unwrap()["Action"].get("CloseWindow").is_some());}
                    let _:bool=first.emit_by_name("enter-notify-event",&[&enter]);settle();settle();
                    let leave=gtk::gdk::Event::new(gtk::gdk::EventType::LeaveNotify);
                    let _:bool=first.emit_by_name("leave-notify-event",&[&leave]);
                    let _:bool=popup.emit_by_name("enter-notify-event",&[&enter]);
                    settle();
                    assert!(popup.is_visible(),"moving to popup hid it");
                    let _:bool=popup.emit_by_name("leave-notify-event",&[&leave]);
                    settle();
                    assert!(!popup.is_visible());
                    // Click while the initial hover timer is pending: no delayed reopen.
                    let _:bool=first.emit_by_name("enter-notify-event",&[&enter]);
                    assert!(first.emit_by_name::<bool>("button-press-event",&[&*press]));
                    let before=requests.lock().unwrap().len();
                    instance.buttons[&1].set_group(vec![(1,"Changed MRU".into()),(2,"Original target".into())],1);
                    assert!(first.emit_by_name::<bool>("button-release-event",&[&*release]));
                    settle();assert!(!popup.is_visible(),"click did not cancel pending preview");
                    let actions=requests.lock().unwrap();
                    assert_eq!(actions.len(),before+1,"first click before Peek must send exactly one action");
                    assert_eq!(actions.last().unwrap()["Action"]["FocusWindow"]["id"],2);
                    drop(actions);
                    // A release without a matching press must not duplicate it.
                    assert!(first.emit_by_name::<bool>("button-release-event",&[&*release]));
                    settle();assert_eq!(requests.lock().unwrap().len(),before+1);
                    let _:bool=first.emit_by_name("enter-notify-event",&[&enter]);settle();
                    let child=popup.child().unwrap();
                    instance.buttons[&1].set_group(vec![(2,"Updated title".into()),(1,"Other title".into())],2);
                    assert_eq!(popup.child().unwrap(),child,"title/order update rebuilt capture widgets");
                    fn labels(widget:&gtk::Widget)->Vec<String>{
                        if let Ok(label)=widget.clone().downcast::<gtk::Label>(){return vec![label.text().to_string()];}
                        widget.clone().downcast::<gtk::Container>().map(|c|c.children().iter().flat_map(labels).collect()).unwrap_or_default()
                    }
                    assert_eq!(labels(&child),vec!["Updated title","Other title"]);
                    instance.buttons[&1].set_group(vec![(2,"Survivor".into())],2);
                    assert_eq!(labels(&popup.child().unwrap()),vec!["Survivor"]);
                    let other=instance.buttons[&3].widget();
                    let _:bool=other.emit_by_name("enter-notify-event",&[&enter]);settle();
                    assert!(!popup.is_visible(),"two popups remained visible");
                    let other_popup=instance.buttons[&3].hover_popup.borrow().clone().unwrap();
                    assert!(other_popup.is_visible());
                    let _:bool=other.emit_by_name("leave-notify-event",&[&leave]);settle();
                    assert!(!other_popup.is_visible());
                }
                first.set_state_flags(gtk::StateFlags::PRELIGHT,false);settle();
                let hover:gtk::gdk::RGBA=first.style_context().style_property_for_state("background-color",gtk::StateFlags::PRELIGHT).get().unwrap();
                assert!((hover.red()-if grouped {18.0/255.0}else{204.0/255.0}).abs()<0.01,"hover color was overridden");
                first.unset_state_flags(gtk::StateFlags::PRELIGHT);
                for (i,id) in instance.displayed.iter().enumerate() {
                    let (x,y)=grouping::cell(i,rows,vertical);
                    assert_eq!(grid.child_at(x,y).unwrap(),*instance.buttons[id].widget());
                }
                assert!(if vertical {window.allocated_width()<=64}else{window.allocated_height()<=64},"short axis expanded unexpectedly");
                // Closing a representative must promote the surviving window, with focus intact.
                let remaining=snapshot().into_iter().filter(|w|w.id!=1).collect();
                MainContext::default().block_on(instance.process_window_snapshot(remaining,filter));
                settle();
                assert!(instance.buttons[&2].widget().style_context().has_class("focused"));
                assert_eq!(grid.children().len(),4);
                unsafe {window.destroy();}
            }
        }
    }
    done.store(true,Ordering::Relaxed);server.join().unwrap();
    unsafe{if let Some(value)=old_socket{std::env::set_var("NIRI_SOCKET",value);}else{std::env::remove_var("NIRI_SOCKET");}}
    std::fs::remove_file(socket).unwrap();

}


#[test]
#[ignore = "requires an isolated GTK display"]
fn pins_follow_workspaces_monitor_mru_and_live_colors() {
    gtk::init().unwrap();
    use std::io::{BufRead,BufReader,Write};
    let socket=std::env::temp_dir().join(format!("adws-pin-click-{}.sock",std::process::id()));
    let listener=std::os::unix::net::UnixListener::bind(&socket).unwrap();
    unsafe {std::env::set_var("NIRI_SOCKET",&socket);}
    let requests=Arc::new(Mutex::new(Vec::new()));let incoming=requests.clone();
    let server=std::thread::spawn(move || {
        for _ in 0..4 {
            let (mut stream,_)=listener.accept().unwrap();
            let mut line=String::new();BufReader::new(stream.try_clone().unwrap()).read_line(&mut line).unwrap();
            incoming.lock().unwrap().push(serde_json::from_str::<serde_json::Value>(&line).unwrap());
            writeln!(stream,"{{\"Ok\":\"Handled\"}}").unwrap();
        }
    });
    let config_home=std::env::temp_dir().join(format!("adws-pins-test-{}",std::process::id()));
    unsafe {std::env::set_var("XDG_CONFIG_HOME",&config_home);}
    std::fs::create_dir_all(config_home.join("adws")).unwrap();
    std::fs::write(pins::path(),serde_json::to_vec(&json!({"version":1,"apps":[
        {"app_id":"foot","desktop_id":"foot.desktop","name":"Terminal"},
        {"app_id":"firefox","desktop_id":"firefox.desktop","name":"Firefox"},
        {"app_id":"code","desktop_id":"code.desktop","name":"Code"},
        {"app_id":"idle","desktop_id":"idle.desktop","name":"Idle app"}
    ]})).unwrap()).unwrap();
    let css=gtk::CssProvider::new();
    gtk::StyleContext::add_provider_for_screen(&gtk::gdk::Screen::default().unwrap(),&css,gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    for vertical in [false,true] {
        css.load_from_data(b".niri-taskbar button.focused {background:#123456;transition:none;}").unwrap();
        let grid=gtk::Grid::new();grid.style_context().add_class("niri-taskbar");
        let window=gtk::Window::new(gtk::WindowType::Toplevel);window.add(&grid);
        let config=serde_json::from_value(json!({"vertical":vertical,"rows":2,"group_windows":false,"show_all_outputs":true,"current_workspace_only":true,"window_peek":false})).unwrap();
        let mut instance=Instance::new(State::new(config),grid.clone());
        let filter=Arc::new(Mutex::new(output::Filter::Only("DP-1".into())));
        let mut stream=niri::WindowSet::new(false);
        stream.with_event(serde_json::from_value(json!({"WorkspacesChanged":{"workspaces":[
            {"id":10,"idx":1,"name":null,"is_urgent":false,"output":"DP-1","is_active":true,"is_focused":true,"active_window_id":2},
            {"id":11,"idx":2,"name":null,"is_urgent":false,"output":"DP-1","is_active":false,"is_focused":false,"active_window_id":3},
            {"id":12,"idx":3,"name":null,"is_urgent":false,"output":"DP-1","is_active":false,"is_focused":false,"active_window_id":6},
            {"id":20,"idx":1,"name":null,"is_urgent":false,"output":"DP-2","is_active":true,"is_focused":false,"active_window_id":4}
        ]}})).unwrap());
        let windows:Vec<_>=[(1,"foot",10,1),(2,"foot",10,2),(3,"firefox",11,2),(4,"code",20,1),(5,"firefox",11,1),(6,"firefox",12,1)]
            .iter().map(|(id,app,workspace,column)|json!({"id":id,"app_id":app,"title":format!("Window {id}"),"pid":null,
                "workspace_id":workspace,"is_focused":*id==2,"is_floating":false,"is_urgent":false,"focus_timestamp":{"secs":id,"nanos":0},
                "layout":{"pos_in_scrolling_layout":[column,1],"tile_size":[800.0,600.0],"window_size":[800,600],"tile_pos_in_workspace_view":[0.0,0.0],"window_offset_in_tile":[0.0,0.0]}})).collect();
        let initial=stream.with_event(serde_json::from_value(json!({"WindowsChanged":{"windows":windows}})).unwrap()).unwrap();
        MainContext::default().block_on(instance.process_window_snapshot(initial,filter.clone()));
        window.show_all();settle();
        assert_eq!(instance.pinned_displayed,vec!["firefox.desktop","code.desktop","idle.desktop"]);
        assert_eq!(instance.displayed.len(),1,"pinned windows group even when ordinary grouping is off");
        assert_eq!(instance.buttons[&1].pin_test_state(),(vec![2,1],2,false));
        assert_eq!(instance.pinned_buttons["firefox.desktop"].pin_test_state(),(vec![6,5,3],6,true));
        assert_eq!(instance.pinned_buttons["code.desktop"].pin_test_state(),(vec![],0,false),"another physical monitor must not count as running");
        assert!(instance.separator.parent().is_some());
        let color=pins::focus_color(&instance.separator);
        assert!((color.red()-18./255.).abs()<0.01,"wrong divider color: {color:?}");
        css.load_from_data(b".niri-taskbar button.focused {background:#ab3456;transition:none;}").unwrap();settle();
        let color=pins::focus_color(&instance.separator);
        assert!((color.red()-171./255.).abs()<0.01,"stale divider color: {color:?}");
        let idle=instance.pinned_buttons["idle.desktop"].widget();
        let enter=gtk::gdk::Event::new(gtk::gdk::EventType::EnterNotify);
        let _:bool=idle.emit_by_name("enter-notify-event",&[&enter]);settle();
        let popup=instance.pinned_buttons["idle.desktop"].hover_popup.borrow().clone().unwrap();
        assert!(popup.is_visible(),"idle pin description must be visible");popup.hide();
        let updated=stream.with_event(serde_json::from_value(json!({"WindowFocusTimestampChanged":{"id":3,"focus_timestamp":{"secs":100,"nanos":0}}})).unwrap()).unwrap();
        MainContext::default().block_on(instance.process_window_snapshot(updated,filter.clone()));
        assert_eq!(instance.pinned_buttons["firefox.desktop"].pin_test_state(),(vec![3,5,6],3,true));
        // One click on the three-dot pin focuses the most recently used remote window.
        instance.pinned_buttons["firefox.desktop"].widget().clone().downcast::<gtk::Button>().unwrap().emit_clicked();
        settle(); // Focus requests run on the worker; wait for the fixture response.
        assert_eq!(requests.lock().unwrap().last().unwrap(),&json!({"Action":{"FocusWindow":{"id":3}}}));
        let unmaps=std::rc::Rc::new(std::cell::Cell::new(0));
        let count=unmaps.clone();
        instance.pinned_buttons["idle.desktop"].widget().connect_unmap(move |_| count.set(count.get()+1));
        // A pending hover on a surviving pin must be cancelled when its position changes.
        let _:bool=instance.pinned_buttons["idle.desktop"].widget().emit_by_name("enter-notify-event",&[&enter]);
        let changed=stream.with_event(niri_ipc::Event::WorkspaceActivated{id:11,focused:true}).unwrap();
        MainContext::default().block_on(instance.process_window_snapshot(changed,filter.clone()));
        settle();
        assert_eq!(unmaps.get(),0,"surviving pins must stay mapped during workspace switches");
        assert!(!popup.is_visible(),"pending Peek must not reopen after its anchor moves");
        assert_eq!(instance.pinned_displayed,vec!["foot.desktop","code.desktop","idle.desktop"]);
        assert_eq!(instance.displayed.len(),1);
        let active=instance.displayed[0];
        assert_eq!(instance.buttons[&active].pin_test_state(),(vec![3,5,6],3,false));
        instance.buttons[&active].widget().clone().downcast::<gtk::Button>().unwrap().emit_clicked();
        settle(); // Focus requests run on the worker; wait for the fixture response.
        assert_eq!(requests.lock().unwrap().last().unwrap(),&json!({"Action":{"FocusWindow":{"id":3}}}));
        for id in [3,5,6] {
            let changed=stream.with_event(niri_ipc::Event::WindowClosed{id}).unwrap();
            MainContext::default().block_on(instance.process_window_snapshot(changed,filter.clone()));
        }
        assert_eq!(instance.pinned_displayed,vec!["foot.desktop","firefox.desktop","code.desktop","idle.desktop"]);
        assert_eq!(instance.pinned_buttons["firefox.desktop"].pin_test_state(),(vec![],0,false));
        assert!(instance.separator.parent().is_some(),"keep the pinned-area divider without active cards");
        instance.pins.retain(|p|p.app_id!="code");
        MainContext::default().block_on(instance.process_window_snapshot(instance.last_snapshot.clone().unwrap(),filter));
        assert!(!instance.pinned_buttons.contains_key("code.desktop"));
        unsafe{window.destroy();}
    }
    server.join().unwrap();std::fs::remove_file(socket).unwrap();
    std::fs::remove_dir_all(config_home).unwrap();
}

#[test]
#[ignore = "requires an isolated GTK display"]
fn repeated_window_cards_release_widgets_and_popovers() {
    gtk::init().unwrap();
    let state = State::new(Config::default());
    let sample = snapshot();
    let host = gtk::Window::new(gtk::WindowType::Toplevel);
    let grid = gtk::Grid::new();
    host.add(&grid);
    host.show_all();
    let mut weak_buttons = Vec::new();
    let mut weak_popovers = Vec::new();
    for round in 0..10 {
        for _ in 0..50 {
            let button = Button::new(&state, &sample[0]);
            weak_buttons.push(button.widget().downgrade());
            weak_popovers.push(button.hover_popup.borrow().as_ref().unwrap().downgrade());
            grid.add(button.widget());
            grid.show_all();
            grid.remove(button.widget());
            drop(button);
        }
        settle();
        let alive_buttons = weak_buttons.iter().filter(|w| w.upgrade().is_some()).count();
        let alive_popovers = weak_popovers.iter().filter(|w| w.upgrade().is_some()).count();
        eprintln!("CARD_LIFETIME round={round} alive_buttons={alive_buttons} alive_popovers={alive_popovers}");
        assert_eq!(alive_buttons, 0, "removed window cards retained GTK objects");
        assert_eq!(alive_popovers, 0, "removed window cards retained popovers");
    }
    unsafe { host.destroy(); }
}

#[test]
#[ignore = "requires an isolated GTK display"]
fn sustained_ipc_flood_keeps_gtk_responsive_and_memory_bounded() {
    use std::io::{BufRead, BufReader, Write};
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::time::{Duration, Instant};
    gtk::init().unwrap();
    let path = std::env::temp_dir().join(format!("adws-flood-{}.sock", std::process::id()));
    let listener = std::os::unix::net::UnixListener::bind(&path).unwrap();
    listener.set_nonblocking(true).unwrap();
    let old_socket = std::env::var_os("NIRI_SOCKET");
    unsafe { std::env::set_var("NIRI_SOCKET", &path); }
    let seconds = std::env::var("ADWS_STRESS_SECONDS").ok().and_then(|v| v.parse().ok()).unwrap_or(30u64);
    let stop = Arc::new(AtomicBool::new(false));
    let sent = Arc::new(AtomicUsize::new(0));
    let done = stop.clone();
    let produced = sent.clone();
    let windows: Vec<_> = snapshot().iter().map(|w| serde_json::to_value(&**w).unwrap()).collect();
    let server = std::thread::spawn(move || {
        let mut jobs = Vec::new();
        while !done.load(Ordering::Relaxed) {
            match listener.accept() {
                Ok((mut socket, _)) => {
                    socket.set_write_timeout(Some(Duration::from_secs(1))).unwrap();
                    socket.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
                    let mut line = String::new();
                    BufReader::new(socket.try_clone().unwrap()).read_line(&mut line).unwrap();
                    if line.contains("EventStream") {
                        writeln!(socket, "{}", json!({"Ok":"Handled"})).unwrap();
                        writeln!(socket, "{}", json!({"WorkspacesChanged":{"workspaces":[{
                            "id":10,"idx":1,"name":null,"output":"DP-1","is_urgent":false,
                            "is_active":true,"is_focused":true,"active_window_id":2}]}})).unwrap();
                        writeln!(socket, "{}", json!({"WindowsChanged":{"windows":windows}})).unwrap();
                        let finished = done.clone(); let count = produced.clone();
                        jobs.push(std::thread::spawn(move || {
                            let until = Instant::now() + Duration::from_secs(seconds);
                            while Instant::now() < until && !finished.load(Ordering::Relaxed) {
                                let mut batch = String::new();
                                for id in (1..=5).cycle().take(50) {
                                    batch.push_str(&format!("{{\"WindowFocusChanged\":{{\"id\":{id}}}}}\n"));
                                }
                                if socket.write_all(batch.as_bytes()).is_err() { break; }
                                count.fetch_add(50, Ordering::Relaxed);
                                std::thread::sleep(Duration::from_millis(10));
                            }
                        }));
                    } else {
                        writeln!(socket, "{}", json!({"Ok":{"Outputs":{}}})).unwrap();
                    }
                }
                Err(_) => std::thread::sleep(Duration::from_millis(2)),
            }
        }
        for job in jobs { job.join().unwrap(); }
    });
    let config: Config = serde_json::from_value(json!({"notifications":{"enabled":false},"window_peek":false})).unwrap();
    let grid = gtk::Grid::new();
    let host = gtk::Window::new(gtk::WindowType::Toplevel);
    host.add(&grid); host.show_all();
    let task = MainContext::default().spawn_local(async move { Instance::new(State::new(config), grid).task().await; });
    let gaps = std::rc::Rc::new(std::cell::RefCell::new(Vec::new()));
    let readings = std::rc::Rc::new(std::cell::RefCell::new(Vec::new()));
    let measured = gaps.clone(); let memory = readings.clone();
    let mut previous = Instant::now(); let started = previous;
    let heartbeat = gtk::glib::timeout_add_local(Duration::from_millis(20), move || {
        let now = Instant::now();
        if started.elapsed() > Duration::from_secs(3) { measured.borrow_mut().push(now.duration_since(previous).as_millis()); }
        previous = now;
        if let Ok(status) = std::fs::read_to_string("/proc/self/status") {
            if let Some(rss) = status.lines().find(|l| l.starts_with("VmRSS:"))
                .and_then(|l| l.split_whitespace().nth(1)).and_then(|v| v.parse::<u64>().ok()) {
                memory.borrow_mut().push((started.elapsed().as_secs(), rss));
            }
        }
        gtk::glib::ControlFlow::Continue
    });
    MainContext::default().block_on(gtk::glib::timeout_future(Duration::from_secs(seconds + 2)));
    stop.store(true, Ordering::Relaxed); task.abort(); heartbeat.remove(); server.join().unwrap();
    let mut gaps = gaps.borrow().clone(); gaps.sort_unstable();
    let memory = readings.borrow();
    let early = memory.iter().find(|(at, _)| *at >= 5).unwrap().1;
    let late = memory.last().unwrap().1;
    let maximum = gaps.last().copied().unwrap_or(9999);
    let p99 = gaps.get(gaps.len()*99/100).copied().unwrap_or(9999);
    eprintln!("IPC_STRESS seconds={seconds} events={} heartbeats={} max_gap_ms={maximum} p99_gap_ms={p99} rss_after_warmup_kib={early} rss_final_kib={late}", sent.load(Ordering::Relaxed), gaps.len());
    unsafe { host.destroy(); if let Some(v)=old_socket {std::env::set_var("NIRI_SOCKET",v);} else {std::env::remove_var("NIRI_SOCKET");} }
    let _ = std::fs::remove_file(path);
    assert!(sent.load(Ordering::Relaxed) > 10_000);
    assert!(maximum < 700, "event flood reproduced the taskbar heartbeat stall");
    assert!(p99 < 100, "GTK repeatedly starved under window events");
    assert!(late.saturating_sub(early) < 32*1024, "memory kept growing after warmup");
}

#[test]
#[ignore = "requires an isolated GTK display"]
fn lyric_width_changes_do_not_reload_unchanged_icons() {
    gtk::init().unwrap();
    for vertical in [false,true] {
        let config=serde_json::from_value(json!({"vertical":vertical})).unwrap();
        let state=State::new(config);
        let button=Button::new(&state,&snapshot()[0]);
        let host=gtk::Window::new(gtk::WindowType::Toplevel);
        host.add(button.widget());host.show_all();settle();
        let icon=button.widget().image().unwrap().downcast::<gtk::Overlay>().unwrap();
        let changes=std::rc::Rc::new(std::cell::Cell::new(0));
        let count=changes.clone();
        icon.connect_add(move |_,_|count.set(count.get()+1));
        let height=button.widget().allocated_height();
        let width=button.widget().allocated_width();
        for extra in [10,30,70,120,60,20,0] {
            button.widget().size_allocate(&gtk::Allocation::new(0,0,
                width+if vertical {0}else{extra},height+if vertical {extra}else{0}));
            settle();
        }
        eprintln!("ICON_WIDTH_CHURN vertical={vertical} reloads={}",changes.get());
        assert_eq!(changes.get(),0,"long-axis changes redecoded the same icon");
        // A real thickness change must still resize the icon.
        button.widget().size_allocate(&gtk::Allocation::new(0,0,
            if vertical {24}else{width},if vertical {height}else{24}));
        settle();
        assert!(changes.get()>0,"thickness changes must update icon pixels");
        unsafe {host.destroy();}
    }
}

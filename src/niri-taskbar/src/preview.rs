//! One cancellable capture helper per visible popup. No GTK-thread blocking I/O.
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
    collections::HashMap,
    ffi::OsStr,
    time::{Duration, Instant},
};
use waybar_cffi::gtk::{self, gio, glib, prelude::*};

// Small, memory-only cache avoids flashing empty cards on a quick revisit.
thread_local! {
    static FRAMES: RefCell<HashMap<u64, (gtk::gdk_pixbuf::Pixbuf, Instant)>> = RefCell::new(HashMap::new());
}
fn cached(id: u64) -> Option<gtk::gdk_pixbuf::Pixbuf> {
    FRAMES.with(|frames| {
        let mut frames = frames.borrow_mut();
        frames.retain(|_, (_, at)| at.elapsed() < Duration::from_secs(15));
        frames.get(&id).map(|(frame, _)| frame.clone())
    })
}
fn remember(id: u64, frame: &gtk::gdk_pixbuf::Pixbuf) {
    FRAMES.with(|frames| {
        let mut frames = frames.borrow_mut();
        if frames.len() >= 24 && !frames.contains_key(&id) {
            if let Some(oldest) = frames
                .iter()
                .min_by_key(|(_, (_, at))| *at)
                .map(|(id, _)| *id)
            {
                frames.remove(&oldest);
            }
        }
        frames.insert(id, (frame.clone(), Instant::now()));
    });
}

// Own both the producer and the pending read. Dropping a preview cancels its
// GTK future immediately, so a late old frame cannot update a replacement.
pub struct Capture {
    process: gio::Subprocess,
    reader: glib::JoinHandle<()>,
}
impl Drop for Capture {
    fn drop(&mut self) {
        self.reader.abort();
        self.process.send_signal(15);
        let exited = Rc::new(Cell::new(false));
        let completed = exited.clone();
        self.process.wait_async(None::<&gio::Cancellable>, move |_| completed.set(true));
        let process = self.process.clone();
        // A helper can still be in synchronous D-Bus/GStreamer initialization
        // before its SIGTERM main-loop handler runs. Bound that shutdown too.
        glib::timeout_add_local_once(Duration::from_millis(250), move || {
            if !exited.get() { process.force_exit(); }
        });
    }
}

pub fn start(
    helper: &str,
    images: Vec<(u64, gtk::Image, gtk::Label)>,
    popup: &gtk::Popover,
) -> Option<Capture> {
    let unavailable = crate::i18n::text("预览暂不可用", "Preview unavailable");
    for (id, image, status) in &images {
        status.set_text(unavailable);
        if let Some(frame) = cached(*id) {
            image.set_from_pixbuf(Some(&frame));
            status.set_opacity(0.);
        }
    }
    if helper.is_empty() || images.is_empty() {
        return None;
    }
    let mut args = vec!["python3".to_string(), helper.to_string()];
    args.extend(images.iter().map(|(id, _, _)| id.to_string()));
    let args: Vec<&OsStr> = args.iter().map(OsStr::new).collect();
    let process = gio::Subprocess::newv(
        &args,
        gio::SubprocessFlags::STDOUT_PIPE | gio::SubprocessFlags::STDERR_SILENCE,
    )
    .ok()?;
    for (_, _, status) in &images {
        status.set_text(crate::i18n::text("正在加载预览…", "Loading preview…"));
    }
    let input = gio::DataInputStream::new(&process.stdout_pipe()?);
    let images: HashMap<_, _> = images
        .into_iter()
        .map(|(id, image, status)| (id, (image.downgrade(), status.downgrade())))
        .collect();
    let weak = popup.downgrade();
    let reader = glib::MainContext::default().spawn_local(async move {
        while let Ok(line) = input.read_line_future(glib::Priority::DEFAULT).await {
            if line.is_empty() {
                break;
            }
            if !weak.upgrade().is_some_and(|p| p.is_visible()) {
                break;
            }
            if line.len() > 512 * 1024 {
                continue;
            }
            let Ok(value) = serde_json::from_slice::<serde_json::Value>(&line) else {
                continue;
            };
            let Some(id) = value["id"].as_u64() else {
                continue;
            };
            let Some(encoded) = value["png"].as_str() else {
                continue;
            };
            let Some(image) = images.get(&id).and_then(|(w, _)| w.upgrade()) else {
                continue;
            };
            let bytes = glib::base64_decode(encoded);
            let loader = gtk::gdk_pixbuf::PixbufLoader::new();
            if loader.write(&bytes).is_ok() && loader.close().is_ok() {
                if let Some(pixbuf) = loader.pixbuf() {
                    remember(id, &pixbuf);
                    image.set_from_pixbuf(Some(&pixbuf));
                    if let Some(status) = images.get(&id).and_then(|(_, w)| w.upgrade()) {
                        status.set_opacity(0.);
                    }
                }
            }
        }
        for (_, (_, status)) in images {
            if let Some(status) = status.upgrade() {
                status.set_text(unavailable);
            }
        }
    });
    Some(Capture { process, reader })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn switching_unloaded_capture_cancels_read_and_bounds_shutdown() {
        gtk::init().unwrap();
        let helper=std::env::temp_dir().join(format!("adws-delayed-preview-{}.py",std::process::id()));
        std::fs::write(&helper,"import signal,time,sys\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nsys.stdout.write('{');sys.stdout.flush()\ntime.sleep(30)\n").unwrap();
        let window=gtk::Window::new(gtk::WindowType::Toplevel);
        let button=gtk::Button::with_label("preview");window.add(&button);window.show_all();
        let popup=gtk::Popover::new(Some(&button));popup.set_modal(false);popup.show();
        let image=gtk::Image::new();let status=gtk::Label::new(None);
        fn pump(ms:u64) {
            let until=Instant::now()+Duration::from_millis(ms);
            while Instant::now()<until {
                while glib::MainContext::default().pending() {glib::MainContext::default().iteration(false);}
                std::thread::sleep(Duration::from_millis(3));
            }
        }
        for _ in 0..3 {
            let capture=start(helper.to_str().unwrap(),vec![(1,image.clone(),status.clone())],&popup).unwrap();
            pump(120);
            let exited=Rc::new(Cell::new(false));let done=exited.clone();
            capture.process.wait_async(None::<&gio::Cancellable>,move |_| done.set(true));
            let began=Instant::now();drop(capture);
            assert!(began.elapsed()<Duration::from_millis(100),"cancel blocked GTK");
            status.set_text("replacement preview");
            let ticks=Rc::new(Cell::new(0));let count=ticks.clone();
            let timer=glib::timeout_add_local(Duration::from_millis(40),move || {count.set(count.get()+1);glib::ControlFlow::Continue});
            pump(650);timer.remove();
            assert!(exited.get(),"old helper survived bounded shutdown");
            assert!(ticks.get()>=8,"replacement preview blocked GTK");
            assert_eq!(status.text(),"replacement preview","old reader overwrote new status");
        }
        unsafe {popup.destroy();window.destroy();}
        let _=std::fs::remove_file(helper);
    }
}

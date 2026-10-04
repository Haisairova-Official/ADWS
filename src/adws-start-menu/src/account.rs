//! One account lookup per graphical login; cache reads and image decoding are asynchronous.
use gtk::{gio, glib, prelude::*};
use serde_json::{json, Value};
use std::{hash::{Hash, Hasher}, io::Write, os::unix::fs::{MetadataExt, OpenOptionsExt}, path::{Path, PathBuf}};

#[derive(Clone)]
struct Account { name: String, avatar: Option<PathBuf> }

fn session_key() -> Option<String> {
    let runtime = std::env::var_os("XDG_RUNTIME_DIR")?;
    let display = std::env::var_os("WAYLAND_DISPLAY")?;
    let socket = PathBuf::from(runtime).join(display);
    let meta = std::fs::metadata(&socket).ok()?;
    // Include the socket generation, so lingering user services and reused
    // display/session names cannot carry an old avatar into a new login.
    Some(format!("{}:{}:{}:{}:{}", std::env::var("XDG_SESSION_ID").unwrap_or_default(),
        socket.display(), meta.ino(), meta.ctime(), meta.ctime_nsec()))
}
fn cache_path(key: &str) -> PathBuf {
    let mut hash = std::collections::hash_map::DefaultHasher::new();
    key.hash(&mut hash);
    glib::user_cache_dir().join("adws").join(format!("account-{:016x}.json", hash.finish()))
}
fn read_cache(path: &Path, key: &str) -> Option<Account> {
    let data: Value = serde_json::from_slice(&std::fs::read(path).ok()?).ok()?;
    if data["session"].as_str()? != key { return None; }
    let avatar = data["avatar"].as_str().map(PathBuf::from);
    if avatar.as_ref().is_some_and(|p| !p.is_file()) { return None; }
    Some(Account { name: data["name"].as_str()?.into(), avatar })
}
fn atomic_write(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = path.with_extension(format!("{}.tmp", std::process::id()));
    let result = (|| {
        let mut file = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&tmp)?;
        file.write_all(bytes)?;
        std::fs::rename(&tmp, path)
    })();
    if result.is_err() { let _ = std::fs::remove_file(tmp); }
    result
}
fn save_cache(path: &Path, key: &str, account: &Account) -> std::io::Result<()> {
    std::fs::create_dir_all(path.parent().unwrap())?;
    let avatar_path = path.with_extension("avatar");
    let mut cached_avatar = None;
    if let Some(source) = &account.avatar {
        // Avoid copying an unexpectedly large user-selected file into cache.
        if std::fs::metadata(source)?.len() <= 8 * 1024 * 1024 {
            atomic_write(&avatar_path, &std::fs::read(source)?)?;
            cached_avatar = Some(avatar_path);
        }
    }
    let data = json!({"session":key,"name":account.name,"avatar":cached_avatar});
    atomic_write(path, &serde_json::to_vec(&data)?)
}

fn circular_avatar(pixbuf: &gtk::gdk_pixbuf::Pixbuf, size: i32, scale: i32) -> Result<gtk::cairo::ImageSurface, gtk::cairo::Error> {
    use gtk::gdk::prelude::GdkContextExt;
    let pixels = size * scale;
    let surface = gtk::cairo::ImageSurface::create(gtk::cairo::Format::ARgb32, pixels, pixels)?;
    let cr = gtk::cairo::Context::new(&surface)?;
    let radius = pixels as f64 / 2.;
    cr.arc(radius, radius, radius, 0., std::f64::consts::TAU);
    cr.clip();
    // Cover the circle using a centered crop, preserving the source aspect ratio.
    let factor = pixels as f64 / pixbuf.width().min(pixbuf.height()) as f64;
    cr.translate((pixels as f64 - pixbuf.width() as f64 * factor) / 2.,
                 (pixels as f64 - pixbuf.height() as f64 * factor) / 2.);
    cr.scale(factor, factor);
    cr.set_source_pixbuf(pixbuf, 0., 0.);
    cr.paint()?;
    surface.set_device_scale(scale as f64, scale as f64);
    Ok(surface)
}

pub fn populate(avatar: &gtk::Image, name: &gtk::Label, round: bool) {
    let size = avatar.pixel_size();
    let scale = if round { avatar.scale_factor().max(1) } else { 1 };
    let avatar = avatar.downgrade(); let name = name.downgrade();
    glib::MainContext::default().spawn_local(async move {
        let Ok((key, cached, mut account, login)) = gio::spawn_blocking(|| {
            let key = session_key();
            let cached = key.as_ref().and_then(|key| read_cache(&cache_path(key), key));
            if let Some(account) = cached {
                return (key, true, account, String::new());
            }
            let login = glib::user_name().to_string_lossy().into_owned();
            let real = glib::real_name().to_string_lossy().into_owned();
            let real = if real.is_empty() || real == "Unknown" { login.clone() } else { real };
            let home = glib::home_dir();
            let avatar = [home.join(".face"), home.join(".face.icon"),
                PathBuf::from("/var/lib/AccountsService/icons").join(&login)]
                .into_iter().find(|path| path.is_file());
            (key, false, Account { name: real, avatar }, login)
        }).await else { return; };
        if !cached {
            if let Some(props) = account_properties(&login).await {
                if let Some(real) = props.get("RealName").and_then(|v| v.str()).filter(|v| !v.trim().is_empty()) {
                    account.name = real.into();
                }
                if let Some(icon) = props.get("IconFile").and_then(|v| v.str()).filter(|v| !v.is_empty()) {
                    account.avatar = Some(PathBuf::from(icon));
                }
            }
            if let Some(key) = key {
                let copy = account.clone();
                let _ = gio::spawn_blocking(move || save_cache(&cache_path(&key), &key, &copy)).await;
            }
        }
        if let Some(label) = name.upgrade() { label.set_text(&account.name); }
        if let Some(path) = account.avatar {
            let file = gio::File::for_path(path);
            if let Ok(stream) = file.read_future(glib::Priority::DEFAULT).await {
                if let Ok(pixbuf) = gtk::gdk_pixbuf::Pixbuf::from_stream_at_scale_future(&stream, size * scale, size * scale, true).await {
                    if let Some(image) = avatar.upgrade() {
                        if round {
                            if let Ok(surface) = circular_avatar(&pixbuf, size, scale) {
                                image.set_from_surface(Some(&surface));
                            }
                        } else { image.set_from_pixbuf(Some(&pixbuf)); }
                    }
                }
            }
        }
        crate::timing(if cached { "account cache" } else { "account refreshed" });
    });
}
async fn account_properties(login: &str) -> Option<std::collections::HashMap<String, glib::Variant>> {
    let bus = gio::bus_get_future(gio::BusType::System).await.ok()?;
    let reply = bus.call_future(Some("org.freedesktop.Accounts"), "/org/freedesktop/Accounts",
        "org.freedesktop.Accounts", "FindUserByName", Some(&(login,).to_variant()), None,
        gio::DBusCallFlags::NONE, 1000).await.ok()?;
    let (path,) = reply.get::<(glib::variant::ObjectPath,)>()?;
    let reply = bus.call_future(Some("org.freedesktop.Accounts"), &path,
        "org.freedesktop.DBus.Properties", "GetAll", Some(&("org.freedesktop.Accounts.User",).to_variant()),
        None, gio::DBusCallFlags::NONE, 1000).await.ok()?;
    let (props,) = reply.get()?;
    Some(props)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn round_avatar_crops_rectangular_source_and_preserves_hidpi_size() {
        gtk::init().unwrap();
        let image = gtk::gdk_pixbuf::Pixbuf::new(gtk::gdk_pixbuf::Colorspace::Rgb, true, 8, 96, 48).unwrap();
        image.fill(0xbc8cffff);
        for scale in [1, 2] {
            let surface = circular_avatar(&image, 48, scale).unwrap();
            assert_eq!(surface.width(), 48 * scale);
            assert_eq!(surface.device_scale(), (scale as f64, scale as f64));
            let result = gtk::gdk::pixbuf_get_from_surface(&surface, 0, 0, 48 * scale, 48 * scale).unwrap();
            let pixels = result.read_pixel_bytes();
            let stride = result.rowstride() as usize;
            let radius = 24 * scale as usize;
            assert_eq!(pixels[3], 0, "square corner must be transparent");
            assert_eq!(pixels[radius * stride + radius * 4 + 3], 255, "center must remain visible");
            assert!(pixels[radius * stride + 4 * scale as usize * 4 + 3] > 240, "cover crop must fill circle");
        }
    }
    #[test]
    fn cached_avatar_survives_source_removal_and_new_login_invalidates() {
        let dir = std::env::temp_dir().join(format!("adws-account-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let source = dir.join("original"); std::fs::write(&source, b"image bytes").unwrap();
        let path = dir.join("account.json");
        save_cache(&path, "login-one", &Account { name: "Example".into(), avatar: Some(source.clone()) }).unwrap();
        std::fs::remove_file(source).unwrap();
        let cached = read_cache(&path, "login-one").unwrap();
        assert_eq!(cached.name, "Example");
        assert_eq!(std::fs::read(cached.avatar.unwrap()).unwrap(), b"image bytes");
        assert!(read_cache(&path, "login-two").is_none());
        std::fs::write(&path, b"incomplete").unwrap();
        assert!(read_cache(&path, "login-one").is_none());
        save_cache(&path, "fallback", &Account { name: "Login".into(), avatar: None }).unwrap();
        assert_eq!(read_cache(&path, "fallback").unwrap().name, "Login");
        std::fs::remove_dir_all(dir).unwrap();
    }
}

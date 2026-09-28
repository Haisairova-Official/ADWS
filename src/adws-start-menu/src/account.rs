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

pub fn populate(avatar: &gtk::Image, name: &gtk::Label) {
    let size = avatar.pixel_size();
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
                if let Ok(pixbuf) = gtk::gdk_pixbuf::Pixbuf::from_stream_at_scale_future(&stream, size, size, true).await {
                    if let Some(image) = avatar.upgrade() { image.set_from_pixbuf(Some(&pixbuf)); }
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

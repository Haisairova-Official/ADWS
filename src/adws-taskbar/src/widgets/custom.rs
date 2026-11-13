use super::{
    actions, field, interpolate, label, markup,
    stream::{self, Worker},
    tooltip,
};
use gtk::{glib, prelude::*};
use serde_json::Value;
use std::{
    any::Any,
    os::unix::{net::UnixStream, process::CommandExt},
    process::{Child, Command, Stdio},
    sync::{Mutex, OnceLock},
    thread::JoinHandle,
    time::Duration,
};

#[derive(Default, PartialEq)]
struct Row {
    text: String,
    tooltip: String,
    classes: Vec<String>,
    alt: String,
    percent: Option<f64>,
}
// GTK strings are NUL-terminated. JSON permits U+0000, including in a
// remote plugin's tooltip and class, so normalize before crossing that ABI.
fn gtk_text(value: &str) -> String {
    value.replace('\0', "�")
}
fn row(line: &[u8], json: bool) -> Option<Row> {
    if !json {
        return Some(Row {
            text: gtk_text(&String::from_utf8_lossy(line)),
            ..Row::default()
        });
    }
    let payload: Value = serde_json::from_slice(line).ok()?;
    let text = gtk_text(payload["text"].as_str()?);
    let classes = match &payload["class"] {
        Value::String(v) => vec![gtk_text(v)],
        Value::Array(list) => list
            .iter()
            .filter_map(Value::as_str)
            .map(gtk_text)
            .collect(),
        _ => vec![],
    };
    Some(Row {
        text,
        tooltip: gtk_text(field(&payload, "tooltip", "")),
        alt: gtk_text(field(&payload, "alt", "")),
        classes,
        percent: payload["percentage"].as_f64(),
    })
}
fn formatted(format: &str, row: &Row, config: &Value) -> String {
    let icon = match &config["format-icons"] {
        Value::Array(items) if !items.is_empty() => {
            let index =
                ((row.percent.unwrap_or(0.).clamp(0., 100.) / 100.) * items.len() as f64) as usize;
            items[index.min(items.len() - 1)].as_str().unwrap_or("")
        }
        Value::Object(items) => items
            .get(&row.alt)
            .or_else(|| items.get("default"))
            .and_then(Value::as_str)
            .unwrap_or(""),
        _ => "",
    };
    interpolate(format, |key| match key {
        "" | "text" => Some(if config["escape"].as_bool() == Some(true) {
            glib::markup_escape_text(&row.text).to_string()
        } else {
            row.text.clone()
        }),
        "alt" => Some(row.alt.clone()),
        "icon" => Some(icon.into()),
        "percentage" => Some(row.percent.unwrap_or(0.).to_string()),
        _ => None,
    })
}
fn reapers() -> &'static Mutex<Vec<JoinHandle<()>>> {
    static REAPERS: OnceLock<Mutex<Vec<JoinHandle<()>>>> = OnceLock::new();
    REAPERS.get_or_init(Mutex::default)
}
fn join_finished(handles: &mut Vec<JoinHandle<()>>) {
    let mut i = 0;
    while i < handles.len() {
        if handles[i].is_finished() {
            let _ = handles.swap_remove(i).join();
        } else {
            i += 1;
        }
    }
}
pub(super) fn finish_shutdown() {
    // All group deadlines start when the widget is removed, independently of
    // the number of outputs. An uninterruptible child must not hang host exit.
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    let mut pending = std::mem::take(&mut *reapers().lock().unwrap());
    while !pending.is_empty() {
        join_finished(&mut pending);
        if pending.is_empty() {
            break;
        }
        if std::time::Instant::now() >= deadline {
            eprintln!(
                "Taskbar: {} children still awaiting kernel exit",
                pending.len()
            );
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}
fn group_has_other_member(leader: i32) -> bool {
    // The exited leader remains a zombie until we wait, reserving its pid/pgid.
    // Check only on termination, so a healthy watchdog exits without incurring
    // the grace delay; a shell descendant ignoring TERM still receives KILL.
    let Ok(entries) = std::fs::read_dir("/proc") else {
        return true;
    };
    entries.flatten().any(|entry| {
        let Some(pid) = entry
            .file_name()
            .to_str()
            .and_then(|v| v.parse::<i32>().ok())
        else {
            return false;
        };
        if pid == leader {
            return false;
        }
        let Ok(stat) = std::fs::read_to_string(entry.path().join("stat")) else {
            return false;
        };
        let Some((_, rest)) = stat.rsplit_once(')') else {
            return false;
        };
        let mut fields = rest.split_whitespace();
        fields.next() != Some("Z")
            && fields.nth(1).and_then(|v| v.parse::<i32>().ok()) == Some(leader)
    })
}
fn cleanup(mut child: Child) {
    use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
    let leader = child.id() as i32;
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, leader, 0) as i32 };
    let pidfd = (raw >= 0).then(|| unsafe { OwnedFd::from_raw_fd(raw) });
    unsafe {
        libc::kill(-leader, libc::SIGTERM);
    }
    let handle = std::thread::spawn(move || {
        let deadline = std::time::Instant::now() + Duration::from_millis(1500);
        if let Some(fd) = pidfd {
            let mut poll = libc::pollfd {
                fd: fd.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            };
            let exited = unsafe { libc::poll(&mut poll, 1, 1500) } > 0;
            if exited && !group_has_other_member(leader) {
                let _ = child.wait();
                return;
            }
        }
        std::thread::sleep(deadline.saturating_duration_since(std::time::Instant::now()));
        unsafe {
            libc::kill(-leader, libc::SIGKILL);
        }
        let _ = child.wait();
    });
    let mut handles = reapers().lock().unwrap();
    join_finished(&mut handles);
    handles.push(handle);
}
fn interval(config: &Value, key: &str) -> Option<Duration> {
    config[key]
        .as_f64()
        .filter(|v| v.is_finite() && *v > 0.)
        .map(|v| Duration::from_secs_f64(v.clamp(0.1, 86400.)))
}
// Mirror the layout generator's shlex.join so a custom shell pipeline or
// redirection can never be mistaken for the generated argv-only runner.
fn runner_argv(command: &str) -> Option<Vec<String>> {
    let args = glib::shell_parse_argv(command)
        .ok()?
        .into_iter()
        .map(|a| a.into_string().ok())
        .collect::<Option<Vec<_>>>()?;
    if !(args.len() == 7 || (args.len() == 9 && args[7] == "--component"))
        || args[0] != "env"
        || !args[1].starts_with("ADWS_PLUGIN_INSTANCE=")
        || args[5] != "--settings-json"
        || std::path::Path::new(&args[3]).file_name()? != "adws_plugin_runner.py"
    {
        return None;
    }
    let canonical = args
        .iter()
        .map(|arg| {
            if !arg.is_empty()
                && arg
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_@%+=:,./-".contains(&b))
            {
                arg.clone()
            } else {
                format!("'{}'", arg.replace('\'', "'\"'\"'"))
            }
        })
        .collect::<Vec<_>>()
        .join(" ");
    (canonical == command).then_some(args)
}
fn run(command: &str, stop: &UnixStream, mut output: impl FnMut(&[u8])) -> std::io::Result<bool> {
    // The generated .mplg runner has an argv-only launch contract. Keep its
    // parent the actual host so the watchdog can notice a crashed host too.
    let mut launch = if let Some(argv) = runner_argv(command) {
        let mut launch = Command::new(&argv[0]);
        launch
            .args(&argv[1..])
            .env("ADWS_PLUGIN_HOST_PID", std::process::id().to_string());
        launch
    } else {
        let mut launch = Command::new("/bin/sh");
        launch.args(["-c", command]);
        launch
    };
    let mut child = launch
        .process_group(0)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .spawn()?;
    let mut stdout = child.stdout.take().unwrap();
    let result = stream::lines(&mut stdout, stop, |line| output(line));
    drop(stdout);
    if !matches!(result, Ok(true)) {
        cleanup(child);
        return result;
    }
    // An exec may close stdout before its process exits. Remain cancellable.
    loop {
        if child.try_wait()?.is_some() {
            return Ok(true);
        }
        if !stream::delay(stop, Duration::from_millis(100)) {
            cleanup(child);
            return Ok(false);
        }
    }
}
pub(super) fn mount(config: &Value, root: &gtk::EventBox) -> Result<Box<dyn Any>, String> {
    let label = label(config, root);
    actions(root, config, false);
    let format = field(config, "format", "{}").to_owned();
    let command = field(config, "exec", "").trim().to_owned();
    let enabled_tip = config["tooltip"].as_bool() != Some(false);
    if command.is_empty() {
        let text = formatted(&format, &Row::default(), config);
        markup(&label, &text);
        if enabled_tip {
            tooltip(root, field(config, "tooltip-format", &text));
        }
        return Ok(Box::new(()));
    }
    let json = field(config, "return-type", "") == "json";
    let repeat = interval(config, "interval").or_else(|| interval(config, "restart-interval"));
    let config = config.clone();
    let root = root.clone();
    let mut previous: Option<Row> = None;
    let mut owned_classes: Vec<String> = Vec::new();
    // show_all() on the host must not expose an empty plugin before its first record.
    root.set_no_show_all(true);
    root.hide();
    let worker = Worker::start(
        "adws-custom",
        move |value: Row| {
            if previous.as_ref() == Some(&value) {
                return;
            }
            let text = formatted(&format, &value, &config);
            markup(&label, &text);
            let ctx = label.style_context();
            owned_classes.retain(|class| {
                let keep = value.classes.contains(class);
                if !keep {
                    ctx.remove_class(class);
                }
                keep
            });
            for class in &value.classes {
                if !class.is_empty() && !ctx.has_class(class) {
                    ctx.add_class(class);
                    owned_classes.push(class.clone());
                }
            }
            if enabled_tip {
                let tip = if let Some(fmt) = config["tooltip-format"].as_str() {
                    formatted(fmt, &value, &config)
                } else if !value.tooltip.is_empty() {
                    value.tooltip.clone()
                } else {
                    text.clone()
                };
                tooltip(&root, &tip);
            }
            root.set_visible(!text.is_empty());
            previous = Some(value);
        },
        move |stop, updates| loop {
            match run(&command, &stop, |line| {
                if let Some(row) = row(line, json) {
                    updates.publish(row);
                }
            }) {
                Ok(false) => break,
                Err(error) => eprintln!("Taskbar custom module: {error}"),
                Ok(true) => (),
            }
            if !repeat.is_some_and(|duration| stream::delay(&stop, duration)) {
                break;
            }
        },
    )
    .map_err(|e| e.to_string())?;
    Ok(Box::new(worker))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn nul_in_plugin_json_does_not_reach_gtk() {
        let row = row(
            br#"{"text":"t\u0000ext","class":["a\u0000b"],"tooltip":"hi\u0000"}"#,
            true,
        )
        .unwrap();
        assert_eq!(row.text, "t�ext");
        assert_eq!(row.classes, ["a�b"]);
        assert_eq!(row.tooltip, "hi�");
    }
    #[test]
    fn watchdog_parent_only_for_generated_argv() {
        let cmd="env ADWS_PLUGIN_INSTANCE=a /usr/bin/python '/opt/AD WS/tools/adws_plugin_runner.py' '/my pack.mplg' --settings-json '{}'";
        assert_eq!(runner_argv(cmd).unwrap()[4], "/my pack.mplg");
        assert!(runner_argv(&format!("{cmd} 2>/tmp/log")).is_none());
        assert!(runner_argv(&cmd.replace("'/my pack.mplg'", "$CUSTOM")).is_none());
    }
    #[test]
    fn cancellation_stops_shell_descendants_that_ignore_term() {
        use std::sync::mpsc;
        let (stop, listen) = UnixStream::pair().unwrap();
        let (tx, rx) = mpsc::channel();
        let worker = std::thread::spawn(move || {
            run(
                "sh -c 'trap \"\" TERM; echo $$; exec sleep 30' & wait",
                &listen,
                |v| {
                    tx.send(std::str::from_utf8(v).unwrap().parse::<u32>().unwrap())
                        .unwrap();
                },
            )
            .unwrap()
        });
        let pid = rx.recv_timeout(Duration::from_secs(3)).unwrap();
        drop(stop);
        assert!(!worker.join().unwrap());
        finish_shutdown();
        let deadline = std::time::Instant::now() + Duration::from_secs(1);
        loop {
            let proc = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap_or_default();
            if proc.is_empty()
                || proc
                    .rsplit(')')
                    .next()
                    .unwrap()
                    .trim_start()
                    .starts_with('Z')
            {
                break;
            }
            assert!(
                std::time::Instant::now() < deadline,
                "descendant still running: {pid}"
            );
            std::thread::sleep(Duration::from_millis(10));
        }
    }
    #[test]
    fn custom_rows_retain_css_and_escape_text() {
        let r = row(
            br#"{"text":"<status>","class":["one","two"],"percentage":100}"#,
            true,
        )
        .unwrap();
        assert_eq!(r.classes, ["one", "two"]);
        assert_eq!(
            formatted(
                "{icon} {}",
                &r,
                &serde_json::json!({"escape":true,"format-icons":["low","high"]})
            ),
            "high &lt;status&gt;"
        );
    }
}

//! Linux plugin supervisor. Python prepares metadata, then execs this process.
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    io,
    os::{fd::AsRawFd, unix::process::CommandExt},
    process::{Child, Command, Stdio},
    sync::atomic::{AtomicI32, Ordering},
    time::{Duration, Instant},
};

const LINE_LIMIT: usize = 1024 * 1024;
const QUEUE_LIMIT: usize = 2 * LINE_LIMIT;
static STOP: AtomicI32 = AtomicI32::new(0);

extern "C" fn stop(signal: libc::c_int) {
    STOP.store(signal, Ordering::Relaxed);
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Spec {
    command: Vec<String>,
    cwd: String,
    id: String,
    rows: bool,
    heartbeat: bool,
    timeout: f64,
    error_text: String,
}

#[derive(Debug)]
enum Failure {
    Closed,
    Cancelled,
    Error(String),
}
impl From<io::Error> for Failure {
    fn from(error: io::Error) -> Self {
        if error.kind() == io::ErrorKind::BrokenPipe {
            Self::Closed
        } else {
            Self::Error(error.to_string())
        }
    }
}
fn invalid(message: impl Into<String>) -> Failure {
    Failure::Error(message.into())
}

struct Nonblocking {
    fd: i32,
    flags: i32,
}
impl Nonblocking {
    fn new(fd: i32) -> io::Result<Self> {
        // SAFETY: fcntl operates on the borrowed descriptor; no pointer is passed.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { fd, flags })
    }
}
impl Drop for Nonblocking {
    fn drop(&mut self) {
        // SAFETY: descriptor remains owned by the enclosing scope.
        unsafe {
            libc::fcntl(self.fd, libc::F_SETFL, self.flags);
        }
    }
}

struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        // The child is the leader of its own process group. Clean up helpers too.
        // SAFETY: the positive child PID identifies the group created below.
        unsafe {
            libc::kill(-(self.0.id() as i32), libc::SIGKILL);
        }
        let _ = self.0.wait();
    }
}

fn validate(data: &[u8], rows: bool) -> Result<Value, Failure> {
    let payload: Value = serde_json::from_slice(data).map_err(|e| invalid(e.to_string()))?;
    let object = payload
        .as_object()
        .ok_or_else(|| invalid("Plugin output must be a JSON object"))?;
    let required = if rows { "primary" } else { "text" };
    if !object.get(required).is_some_and(Value::is_string) {
        return Err(invalid(format!("Missing text field: {required}")));
    }
    for field in ["text", "primary", "secondary", "tooltip", "alt"] {
        if object.get(field).is_some_and(|v| !v.is_string()) {
            return Err(invalid(format!("Invalid text field: {field}")));
        }
    }
    if let Some(classes) = object.get("class") {
        if !classes.is_string()
            && !classes
                .as_array()
                .is_some_and(|v| v.iter().all(Value::is_string))
        {
            return Err(invalid("Invalid CSS class"));
        }
    }
    if let Some(value) = object.get("percentage") {
        if !value
            .as_f64()
            .is_some_and(|v| v.is_finite() && (0.0..=100.0).contains(&v))
        {
            return Err(invalid("Invalid percentage"));
        }
    }
    Ok(payload)
}

fn enqueue(queue: &mut VecDeque<u8>, line: &[u8]) -> Result<(), Failure> {
    if queue.len() + line.len() + 1 > QUEUE_LIMIT {
        return Err(invalid("Plugin output consumer is too slow"));
    }
    queue.extend(line);
    queue.push_back(b'\n');
    Ok(())
}
fn flush(fd: i32, queue: &mut VecDeque<u8>) -> Result<(), Failure> {
    if queue.is_empty() {
        return Ok(());
    }
    let chunk = queue.as_slices().0;
    // SAFETY: the slice is live and fd is borrowed; write cannot outlive this call.
    let count = unsafe { libc::write(fd, chunk.as_ptr().cast(), chunk.len()) };
    if count < 0 {
        let error = io::Error::last_os_error();
        if matches!(
            error.kind(),
            io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
        ) {
            return Ok(());
        }
        return Err(error.into());
    }
    if count == 0 {
        return Err(Failure::Closed);
    }
    queue.drain(..count as usize);
    Ok(())
}
fn line(data: &[u8], stderr: bool, spec: &Spec, queue: &mut VecDeque<u8>) -> Result<(), Failure> {
    if stderr {
        enqueue(
            queue,
            format!("[plugin:{}] {}", spec.id, String::from_utf8_lossy(data)).as_bytes(),
        )
    } else {
        let payload = validate(data, spec.rows)?;
        enqueue(
            queue,
            &serde_json::to_vec(&payload).map_err(|e| invalid(e.to_string()))?,
        )
    }
}

fn supervise(spec: &Spec) -> Result<(), Failure> {
    if spec.command.is_empty() || !spec.timeout.is_finite() || spec.timeout <= 0.0 {
        return Err(invalid("Invalid command or timeout"));
    }
    let timeout =
        Duration::try_from_secs_f64(spec.timeout).map_err(|_| invalid("Invalid timeout"))?;
    let first_deadline = Instant::now()
        .checked_add(timeout)
        .ok_or_else(|| invalid("Invalid timeout"))?;
    if STOP.load(Ordering::Relaxed) != 0 {
        return Err(Failure::Cancelled);
    }
    let mut child = Process(
        Command::new(&spec.command[0])
            .args(&spec.command[1..])
            .current_dir(&spec.cwd)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn()?,
    );
    let stdout = child.0.stdout.take().unwrap();
    let stderr = child.0.stderr.take().unwrap();
    let input = [stdout.as_raw_fd(), stderr.as_raw_fd()];
    let _in0 = Nonblocking::new(input[0])?;
    let _in1 = Nonblocking::new(input[1])?;
    let mut open = [true, true];
    let mut buffers = [Vec::new(), Vec::new()];
    let mut queues = [VecDeque::new(), VecDeque::new()];
    let mut deadline = Some(first_deadline);
    let mut exit_deadline = None;
    let mut status = None;
    let mut records = 0;
    loop {
        if STOP.load(Ordering::Relaxed) != 0 {
            return Err(Failure::Cancelled);
        }
        if status.is_none() {
            status = child.0.try_wait()?;
        }
        if (status.is_some() || !open.iter().any(|v| *v)) && exit_deadline.is_none() {
            exit_deadline = Instant::now().checked_add(timeout);
        }
        if !open.iter().any(|v| *v) && queues.iter().all(VecDeque::is_empty) {
            if let Some(code) = status {
                return if code.success() && records > 0 {
                    Ok(())
                } else {
                    Err(invalid(format!(
                        "Plugin exited with status {code}; records={records}"
                    )))
                };
            }
        }
        let now = Instant::now();
        if deadline.is_some_and(|d| now >= d) || exit_deadline.is_some_and(|d| now >= d) {
            return Err(invalid("Plugin output or exit timed out"));
        }
        let mut polls = [
            libc::pollfd {
                fd: if open[0] { input[0] } else { -1 },
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: if open[1] { input[1] } else { -1 },
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: 1,
                events: if queues[0].is_empty() {
                    0
                } else {
                    libc::POLLOUT
                },
                revents: 0,
            },
            libc::pollfd {
                fd: 2,
                events: if queues[1].is_empty() {
                    0
                } else {
                    libc::POLLOUT
                },
                revents: 0,
            },
        ];
        // SAFETY: poll receives a valid, writable array of exactly four entries.
        let ready = unsafe { libc::poll(polls.as_mut_ptr(), polls.len() as _, 50) };
        if ready < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error.into());
        }
        for index in 0..2 {
            let event = polls[index + 2].revents;
            if event & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
                return Err(Failure::Closed);
            }
            if event & libc::POLLOUT != 0 {
                flush(index as i32 + 1, &mut queues[index])?;
            }
            if polls[index].revents == 0 {
                continue;
            }
            let mut chunk = [0u8; 65536];
            // SAFETY: the buffer is writable and lives until read returns.
            let size = unsafe { libc::read(input[index], chunk.as_mut_ptr().cast(), chunk.len()) };
            if size < 0 {
                let error = io::Error::last_os_error();
                if matches!(
                    error.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                ) {
                    continue;
                }
                return Err(error.into());
            }
            if size == 0 {
                open[index] = false;
            } else {
                buffers[index].extend_from_slice(&chunk[..size as usize]);
            }
            while let Some(end) = buffers[index].iter().position(|b| *b == b'\n') {
                if end > LINE_LIMIT {
                    return Err(invalid("Plugin output exceeds 1 MiB"));
                }
                let data: Vec<_> = buffers[index].drain(..=end).collect();
                line(&data[..end], index == 1, spec, &mut queues[index])?;
                if index == 0 {
                    records += 1;
                    deadline = if spec.heartbeat {
                        Instant::now().checked_add(timeout)
                    } else {
                        None
                    };
                }
            }
            if buffers[index].len() > LINE_LIMIT {
                return Err(invalid("Plugin output exceeds 1 MiB"));
            }
            if !open[index] && !buffers[index].is_empty() {
                line(&buffers[index], index == 1, spec, &mut queues[index])?;
                buffers[index].clear();
                if index == 0 {
                    records += 1;
                }
            }
        }
    }
}

fn bounded_output(fd: i32, data: &[u8]) -> Result<(), Failure> {
    let mut queue = VecDeque::from(data.to_vec());
    let deadline = Instant::now() + Duration::from_millis(500);
    while !queue.is_empty() && Instant::now() < deadline {
        if STOP.load(Ordering::Relaxed) != 0 {
            return Err(Failure::Cancelled);
        }
        flush(fd, &mut queue)?;
        if !queue.is_empty() {
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    Ok(())
}
fn main() -> std::process::ExitCode {
    // SAFETY: handlers only store a lock-free atomic; SIGPIPE is handled as EPIPE.
    unsafe {
        libc::signal(libc::SIGTERM, stop as *const () as libc::sighandler_t);
        libc::signal(libc::SIGINT, stop as *const () as libc::sighandler_t);
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec-json" {
        eprintln!("Usage: adws-plugin-runner --spec-json JSON (internal ADWS interface)");
        return 2.into();
    }
    let spec: Spec = match serde_json::from_str(&args[2]) {
        Ok(spec) => spec,
        Err(error) => {
            eprintln!("Invalid launch specification: {error}");
            return 2.into();
        }
    };
    let Ok(_out) = Nonblocking::new(1) else {
        return 0.into();
    };
    let Ok(_err) = Nonblocking::new(2) else {
        return 0.into();
    };
    match supervise(&spec) {
        Ok(()) | Err(Failure::Closed | Failure::Cancelled) => 0.into(),
        Err(Failure::Error(error)) => {
            let _ = bounded_output(2, format!("[plugin:{}] {error}\n", spec.id).as_bytes());
            let row = json!({"text":spec.error_text,"primary":spec.error_text,"secondary":"", "tooltip":spec.error_text,"class":"error"});
            match bounded_output(1, format!("{row}\n").as_bytes()) {
                Err(Failure::Closed | Failure::Cancelled) => 0.into(),
                _ => 1.into(),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn validates_bilingual_and_text_payloads() {
        assert!(validate(
            br#"{"text":"hello","class":["a","b"],"percentage":100}"#,
            false
        )
        .is_ok());
        assert!(validate(
            "{\"primary\":\"原文\",\"secondary\":\"译文\"}".as_bytes(),
            true
        )
        .is_ok());
        for payload in [
            r#"[]"#,
            r#"{"text":7}"#,
            r#"{"text":"ok","class":[0]}"#,
            r#"{"text":"ok","percentage":true}"#,
            r#"{"text":"ok","percentage":101}"#,
        ] {
            assert!(validate(payload.as_bytes(), false).is_err());
        }
    }
    #[test]
    fn rejects_huge_numbers_and_bounds_queue() {
        let payload = format!("{{\"text\":\"ok\",\"percentage\":{}}}", "9".repeat(1000));
        assert!(validate(payload.as_bytes(), false).is_err());
        let mut queue = VecDeque::new();
        assert!(enqueue(&mut queue, &vec![0; QUEUE_LIMIT]).is_err());
        assert!(queue.is_empty());
    }
}

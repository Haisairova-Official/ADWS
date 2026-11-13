mod cffi;
mod host;
mod style;
mod widgets;

use std::{env, path::PathBuf};

fn run() -> Result<(), String> {
    let usage = "Usage: adws-taskbar --config EXPANDED-BAR.json --style STYLE.css [--check]";
    let mut args = env::args_os().skip(1);
    let (mut config, mut style, mut check) = (None, None, false);
    while let Some(arg) = args.next() {
        match arg.to_str() {
            Some("--config") if config.is_none() => {
                config = Some(PathBuf::from(args.next().ok_or(usage)?))
            }
            Some("--style") if style.is_none() => {
                style = Some(PathBuf::from(args.next().ok_or(usage)?))
            }
            Some("--check") => check = true,
            Some("--help" | "-h") => {
                println!("{usage}");
                return Ok(());
            }
            _ => return Err(usage.to_owned()),
        }
    }
    let config_path = config.ok_or(usage)?;
    let config = host::Config::read(&config_path)?;
    config.validate_modules()?;
    let style = env::current_dir()
        .map_err(|e| e.to_string())?
        .join(style.ok_or(usage)?);
    if !style.is_file() {
        return Err(format!("Expected a stylesheet file: {}", style.display()));
    }
    if check {
        return Ok(());
    }
    let result = host::run(config, &config_path, &style);
    cffi::finish_shutdown();
    widgets::finish_shutdown();
    result
}

fn main() -> std::process::ExitCode {
    match run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("adws-taskbar: {error}");
            std::process::ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
#[test]
#[ignore = "requires an isolated GTK display, xdotool and /proc"]
fn gtk_display_regressions() {
    // libtest uses a new thread per test. GTK permits only the thread that
    // initialized the display to run these interactive checks.
    style::tests::buttons_inherit_the_bar_foreground_but_respect_user_colors();
    widgets::tests::live_widget_stream_and_launch();
    widgets::tests::repeated_stream_mounts_release_workers_and_signal_sources();
}

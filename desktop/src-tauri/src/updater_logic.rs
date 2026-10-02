//! Pure decisions for automatic updates: when to install, where, and how.
//!
//! Purpose    : Everything the updater decides that does not need a window,
//!              a socket or a process, so `cargo test` covers it.
//! Inputs     : GET /api/update/status and POST /api/update/apply bodies, the
//!              running executable's path, how long the app has been unused.
//! Outputs    : `UpdateStatus`, `Apply`, `should_auto_install`, `bundle_parent`,
//!              `script_args`, `tray_label`.
//! Constraints: An app not running from a bundle named `Find+.app` (a dev run
//!              out of target/) never installs anything.

use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::Value;

/// Unused this long with no Find+ window on screen: safe to restart.
pub const IDLE_HIDDEN: Duration = Duration::from_secs(5 * 60);
/// A window left open but not focused this long also counts as unused.
pub const IDLE_VISIBLE: Duration = Duration::from_secs(30 * 60);
/// After an automatic attempt fails, wait this long before trying again.
pub const RETRY_AFTER: Duration = Duration::from_secs(60 * 60);

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UpdateStatus {
    pub staged_version: Option<String>,
    pub auto_install_ready: bool,
}

/// Pure: the fields the shell needs from one /api/update/status body.
pub fn parse_status(body: &Value) -> UpdateStatus {
    UpdateStatus {
        staged_version: body
            .get("staged_version")
            .and_then(Value::as_str)
            .map(str::to_string),
        auto_install_ready: body.get("auto_install_ready").and_then(Value::as_bool) == Some(true),
    }
}

/// What POST /api/update/apply hands over: the build and where to report.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Apply {
    pub kind: String,
    pub path: String,
    pub version: String,
    pub result_file: String,
}

/// Pure: an apply body, or the daemon's plain-words reason.
pub fn parse_apply(http_status: u16, body: &Value) -> Result<Apply, String> {
    let text = |k: &str| {
        body.get(k)
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string()
    };
    if http_status != 200 {
        let detail = text("detail");
        return Err(if detail.is_empty() {
            format!("Find+ answered {http_status}.")
        } else {
            detail
        });
    }
    let apply = Apply {
        kind: text("kind"),
        path: text("path"),
        version: text("version"),
        result_file: text("result_file"),
    };
    if !matches!(apply.kind.as_str(), "dmg" | "app") || apply.path.is_empty() {
        return Err("Find+ sent an update it could not read.".into());
    }
    if apply.result_file.is_empty() {
        return Err("Find+ sent an update it could not read.".into());
    }
    Ok(apply)
}

/// Pure: install by itself now? Ready, unused long enough, not paused by a failure.
pub fn should_auto_install(
    status: &UpdateStatus,
    window_visible: bool,
    unused_for: Duration,
    paused: bool,
) -> bool {
    let needed = if window_visible {
        IDLE_VISIBLE
    } else {
        IDLE_HIDDEN
    };
    status.auto_install_ready && status.staged_version.is_some() && !paused && unused_for >= needed
}

/// Pure: the folder holding the running `Find+.app`, from the executable's path
/// (`<dir>/Find+.app/Contents/MacOS/<exe>`). None outside an installed bundle.
pub fn bundle_parent(exe: &Path) -> Option<PathBuf> {
    let app = exe.parent()?.parent()?.parent()?;
    let named = app.file_name().and_then(|n| n.to_str()) == Some("Find+.app");
    let contents = exe.parent()?.parent()?.file_name().and_then(|n| n.to_str()) == Some("Contents");
    if named && contents {
        app.parent().map(Path::to_path_buf)
    } else {
        None
    }
}

/// Pure: update-app.sh's arguments for one apply. `wait_pid` None = --verify-only.
pub fn script_args(script: &Path, apply: &Apply, wait_pid: Option<u32>) -> Vec<String> {
    let flag = if apply.kind == "app" {
        "--app"
    } else {
        "--dmg"
    };
    let mut args = vec![
        script.display().to_string(),
        flag.to_string(),
        apply.path.clone(),
    ];
    match wait_pid {
        None => args.push("--verify-only".into()),
        Some(pid) => args.extend([
            "--wait-pid".to_string(),
            pid.to_string(),
            "--result".to_string(),
            apply.result_file.clone(),
        ]),
    }
    args
}

/// Pure: the tray item for a staged update.
pub fn tray_label(version: &str) -> String {
    format!("Restart to update (v{version})")
}

/// Pure: the last line update-app.sh printed, for a short error.
pub fn last_line(output: &str) -> String {
    let line = output
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .unwrap_or("");
    line.trim().trim_start_matches("update: ").to_string()
}

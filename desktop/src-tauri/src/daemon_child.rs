//! The child sidecar Find+ owns: spawning `findplus-daemon serve
//! --foreground`, tracking its pid, and killing it on Quit.
//!
//! Purpose    : Keep exactly one app-owned daemon process and make its
//!              liveness observable, so daemon.rs never spawns a second one
//!              and tray.rs can stop it cleanly before the app exits.
//! Constraints: Split out of daemon.rs to keep that file under the 300-line
//!              cap (PRI hard rule 7).

use std::process::Command;
use std::sync::{Mutex, OnceLock};

use super::daemon_util;

static CHILD_PID: OnceLock<Mutex<Option<u32>>> = OnceLock::new();

/// Spawn `findplus-daemon serve --foreground` as a child, logging to
/// ~/.findplus/logs/app-sidecar.log. FINDPLUS_STATE_DIR is left unset so the
/// sidecar defaults to the real state dir, matching the CLI's own default.
pub fn spawn_sidecar(app: &tauri::AppHandle) {
    use std::fs::OpenOptions;
    use tauri_plugin_shell::ShellExt;

    let Some(home) = dirs::home_dir() else {
        log::error!("spawn_sidecar: no home directory");
        return;
    };
    let log_dir = home.join(".findplus/logs");
    if let Err(e) = std::fs::create_dir_all(&log_dir) {
        log::error!("spawn_sidecar: could not create log dir: {e}");
        return;
    }
    let log_path = log_dir.join("app-sidecar.log");
    let _log_file = OpenOptions::new().create(true).append(true).open(&log_path);

    let shell = app.shell();
    let command = match shell.sidecar("findplus-daemon") {
        Ok(cmd) => cmd,
        Err(e) => {
            log::error!("spawn_sidecar: sidecar() failed: {e}");
            return;
        }
    };
    match command.args(["serve", "--foreground"]).spawn() {
        Ok((_receiver, child)) => {
            CHILD_PID
                .get_or_init(|| Mutex::new(None))
                .lock()
                .unwrap()
                .replace(child.pid());
        }
        Err(e) => log::error!("spawn_sidecar: failed to spawn: {e}"),
    }
}

/// True when a child sidecar PID is tracked and the process is still alive.
pub fn child_running() -> bool {
    let pid = *CHILD_PID.get_or_init(|| Mutex::new(None)).lock().unwrap();
    match pid {
        Some(p) => daemon_util::pid_alive(p),
        None => false,
    }
}

/// Kill the tracked child sidecar, if any, and clear CHILD_PID.
pub fn stop_child() {
    let mut guard = CHILD_PID.get_or_init(|| Mutex::new(None)).lock().unwrap();
    if let Some(pid) = guard.take() {
        let _ = Command::new("/bin/kill").arg(pid.to_string()).status();
    }
}

//! Daemon supervisor: probes the local API, decides whether to attach,
//! kickstart a LaunchAgent, or spawn a child sidecar, and never runs two
//! daemons at once. Runs continuously so a crash after a successful attach
//! is detected, not just the state at launch.
//!
//! Purpose    : Implement the 5-row decision table in
//!              specs/desktop-app.md § Daemon supervision decision table,
//!              plus the edge cases in PLAN.md § E13-T8 (port squatter,
//!              crash-then-amber, version mismatch).
//! Inputs     : GET /api/health (2 s timeout), ~/.findplus/daemon.json,
//!              ~/Library/LaunchAgents/com.acamarata.findplus.plist.
//! Outputs    : Attaches to, kickstarts, or spawns the daemon; emits
//!              "daemon-another-app" / "daemon-crashed" for tray.rs.
//! Constraints: The branching logic is a pure function (`decide`) so it is
//!              unit-testable without touching the network or the filesystem.

use serde_json::Value;
use std::process::Command;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;
use tauri::Emitter;

#[path = "daemon_util.rs"]
mod daemon_util;

const PORT: u16 = 8647;
const APP_VERSION: &str = env!("FINDPLUS_VERSION");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DaemonState {
    Attached,
    AnotherApp,
    WaitingLaunchAgent,
    WaitingSidecar,
    WaitingPid,
    // specs/desktop-app.md's decision table has exactly 5 rows; decide()
    // never returns Down directly — start() concludes Down itself after a
    // WaitingPid re-probe times out (see the DaemonDownReason::Crashed
    // path). The variant stays on the enum because it is part of the
    // documented state set and daemon.rs (and DoD greps) reference it.
    #[allow(dead_code)]
    Down,
}

/// Whether the last observed Down state followed a successful attach (a
/// crash, recoverable with "Restart daemon") or is the normal not-yet-
/// started/unrecoverable case (no such menu item).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DaemonDownReason {
    Normal,
    Crashed,
}

static DOWN_REASON: OnceLock<Mutex<DaemonDownReason>> = OnceLock::new();
static ANOTHER_APP_LINE: OnceLock<Mutex<Option<String>>> = OnceLock::new();
static CHILD_PID: OnceLock<Mutex<Option<u32>>> = OnceLock::new();

fn down_reason_cell() -> &'static Mutex<DaemonDownReason> {
    DOWN_REASON.get_or_init(|| Mutex::new(DaemonDownReason::Normal))
}

pub fn down_reason() -> DaemonDownReason {
    *down_reason_cell().lock().unwrap()
}

pub fn down_reason_is_crashed() -> bool {
    down_reason() == DaemonDownReason::Crashed
}

fn set_down_reason(reason: DaemonDownReason) {
    *down_reason_cell().lock().unwrap() = reason;
}

/// The line to show when another program holds port 8647, if that is the
/// current state; None once the daemon attaches normally.
pub fn another_app_line() -> Option<String> {
    ANOTHER_APP_LINE
        .get_or_init(|| Mutex::new(None))
        .lock()
        .unwrap()
        .clone()
}

fn set_another_app_line(line: Option<String>) {
    *ANOTHER_APP_LINE.get_or_init(|| Mutex::new(None)).lock().unwrap() = line;
}

/// Probe GET /api/health with a 2 s timeout. Returns (app, version) on 200,
/// None on any error (connection refused, timeout, non-200, unparsable).
pub fn probe(port: u16) -> Option<(String, String)> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .ok()?;
    let resp = client
        .get(format!("http://127.0.0.1:{port}/api/health"))
        .send()
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let body: Value = resp.json().ok()?;
    let app = body.get("app").and_then(|v| v.as_str())?.to_string();
    let version = body
        .get("version")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    Some((app, version))
}

/// True when the user-level LaunchAgent plist exists.
pub fn launch_agent_installed() -> bool {
    dirs::home_dir()
        .map(|h| {
            h.join("Library/LaunchAgents/com.acamarata.findplus.plist")
                .exists()
        })
        .unwrap_or(false)
}

/// `launchctl kickstart -k gui/$UID/com.acamarata.findplus`.
pub fn kickstart() {
    let uid = daemon_util::current_uid();
    let _ = Command::new("launchctl")
        .args([
            "kickstart",
            "-k",
            &format!("gui/{uid}/com.acamarata.findplus"),
        ])
        .status();
}

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
    let _log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path);

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

/// Pure decision function over the 5-row table in specs/desktop-app.md.
/// `probe_result`: Some((app_name, version)) on a 200 health response.
/// `daemon_json_pid`: the pid recorded in daemon.json, if the file exists
/// and parses, and only when that pid is currently alive (the caller
/// resolves liveness before calling this).
/// `launch_agent`: whether the LaunchAgent plist exists.
pub fn decide(
    probe_result: Option<(&str, &str)>,
    daemon_json_pid: Option<u32>,
    launch_agent: bool,
) -> DaemonState {
    match probe_result {
        Some(("findplus", _)) => DaemonState::Attached,
        Some(_other) => DaemonState::AnotherApp,
        None => match daemon_json_pid {
            Some(_pid) => DaemonState::WaitingPid,
            None if launch_agent => DaemonState::WaitingLaunchAgent,
            None => DaemonState::WaitingSidecar,
        },
    }
}

/// Run the supervisor continuously in a background thread: an initial
/// decision (attach / kickstart / spawn), then a 45 s poll loop so a crash
/// after a successful attach is detected (DaemonDownReason::Crashed) rather
/// than only checked once at launch.
pub fn start(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let mut was_attached = false;
        loop {
            let probed = probe(PORT);
            let probe_tuple = probed.as_ref().map(|(a, v)| (a.as_str(), v.as_str()));
            let pid_alive_now = daemon_util::read_daemon_json_pid().filter(|p| daemon_util::pid_alive(*p));
            let agent = launch_agent_installed();

            match decide(probe_tuple, pid_alive_now, agent) {
                DaemonState::Attached => {
                    if let Some((_app_name, version)) = &probed {
                        if version != APP_VERSION && !version.is_empty() {
                            log::warn!("daemon: CLI daemon v{version} (app is v{APP_VERSION})");
                        }
                    }
                    was_attached = true;
                    set_down_reason(DaemonDownReason::Normal);
                    set_another_app_line(None);
                }
                DaemonState::AnotherApp => {
                    let line = "Port 8647 is used by another program".to_string();
                    set_another_app_line(Some(line));
                    let _ = app.emit("daemon-another-app", ());
                }
                DaemonState::WaitingLaunchAgent => {
                    kickstart();
                    reprobe(PORT);
                }
                DaemonState::WaitingSidecar => {
                    spawn_sidecar(&app);
                    reprobe(PORT);
                }
                DaemonState::WaitingPid => {
                    std::thread::sleep(Duration::from_secs(20));
                    if probe(PORT).is_none() {
                        if was_attached {
                            set_down_reason(DaemonDownReason::Crashed);
                            let _ = app.emit("daemon-crashed", ());
                        }
                        log::warn!("daemon: Down after waiting for a live pid");
                    }
                }
                DaemonState::Down => {}
            }

            std::thread::sleep(Duration::from_secs(45));
        }
    });
}

fn reprobe(port: u16) {
    for _ in 0..20 {
        if probe(port).is_some() {
            return;
        }
        std::thread::sleep(Duration::from_secs(1));
    }
    log::warn!("daemon: re-probe timed out after 20s");
}

#[cfg(test)]
#[path = "daemon_tests.rs"]
mod tests;

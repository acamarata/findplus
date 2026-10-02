//! Automatic updates in the shell: watch for a staged update, install it while
//! Find+ is not in use, and offer "Restart to update" until then.
//!
//! Purpose    : The daemon finds, downloads and verifies updates; this loop
//!              decides WHEN to install (updater_logic.rs) and the install
//!              itself lives in updater_apply.rs.
//! Inputs     : GET /api/update/status every minute; window focus every 15 s.
//! Outputs    : "update-staged" for tray.rs when the staged version changes;
//!              the `apply_update` command for the dashboard (main window only).
//! Constraints: Installs by itself only when the daemon says
//!              `auto_install_ready` (switch on, verified build, no failed
//!              attempt for it) and no window has been used for a while. A
//!              failed automatic attempt pauses automatic tries for an hour.

use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager};

#[path = "updater_apply.rs"]
mod apply;
#[path = "updater_logic.rs"]
pub mod logic;

use logic::{parse_status, should_auto_install, UpdateStatus, RETRY_AFTER};

const TICK: Duration = Duration::from_secs(15);
const STATUS_EVERY: u32 = 4; // ticks: one status read a minute

static STAGED: OnceLock<Mutex<Option<String>>> = OnceLock::new();

fn staged_cell() -> &'static Mutex<Option<String>> {
    STAGED.get_or_init(|| Mutex::new(None))
}

/// The staged version, for the tray's "Restart to update (vX)" item.
pub fn staged_version() -> Option<String> {
    staged_cell().lock().unwrap().clone()
}

fn fetch_status() -> Option<UpdateStatus> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .ok()?;
    let url = format!("{}/api/update/status", crate::daemon::daemon_base());
    let resp = client.get(url).send().ok()?;
    if !resp.status().is_success() {
        return None;
    }
    resp.json::<serde_json::Value>()
        .ok()
        .map(|b| parse_status(&b))
}

/// (any window on screen, any window focused), the splash aside.
fn window_activity(app: &AppHandle) -> (bool, bool) {
    let mut visible = false;
    let mut focused = false;
    for (label, win) in app.webview_windows() {
        if label == "splash" {
            continue;
        }
        visible |= win.is_visible().unwrap_or(false);
        focused |= win.is_focused().unwrap_or(false);
    }
    (visible, focused)
}

fn publish(app: &AppHandle, status: &UpdateStatus) {
    let mut cell = staged_cell().lock().unwrap();
    if *cell != status.staged_version {
        cell.clone_from(&status.staged_version);
        drop(cell);
        let _ = app.emit("update-staged", status.staged_version.clone());
    }
}

/// Start the loop on its own thread.
pub fn start(app: AppHandle) {
    std::thread::spawn(move || {
        let mut last_used = Instant::now();
        let mut paused_until: Option<Instant> = None;
        let mut status = UpdateStatus::default();
        let mut tick: u32 = 0;
        loop {
            let (visible, focused) = window_activity(&app);
            if focused {
                last_used = Instant::now();
            }
            if tick.is_multiple_of(STATUS_EVERY) {
                if let Some(s) = fetch_status() {
                    publish(&app, &s);
                    status = s;
                }
            }
            let paused = paused_until.is_some_and(|t| Instant::now() < t);
            if should_auto_install(&status, visible, last_used.elapsed(), paused)
                && apply::install().is_err()
            {
                paused_until = Some(Instant::now() + RETRY_AFTER);
            }
            tick = tick.wrapping_add(1);
            std::thread::sleep(TICK);
        }
    });
}

/// The tray's "Restart to update" item: install now, or say why not.
pub fn install_from_tray(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || {
        if let Err(reason) = apply::install() {
            use tauri_plugin_dialog::DialogExt;
            app.dialog()
                .message(format!("Find+ could not update: {reason}"))
                .title("Find+")
                .show(|_| {});
        }
    });
}

/// The dashboard's Restart to update / Update now. Main window only.
#[tauri::command(async)]
pub fn apply_update(webview: tauri::Webview) -> Result<String, String> {
    if webview.label() != "main" {
        return Err("not_main_window".into());
    }
    apply::install()
}

#[cfg(test)]
#[path = "updater_tests.rs"]
mod tests;

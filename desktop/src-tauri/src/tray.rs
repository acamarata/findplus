//! Tray icon: the menu-bar dropdown, status dot, and the Quit confirm flow.
//!
//! Purpose    : Build the menu from the current Status plus the daemon's
//!              own edge-case signals (port squatter, crash) and wire every
//!              item's action.
//! Inputs     : "status-update" (status::start()), "daemon-another-app" /
//!              "daemon-crashed" (daemon::start()).
//! Outputs    : A rebuilt tray menu and tray icon on every update.
//! Constraints: Menu item order and the Quit dialog wording are normative
//!              (specs/desktop-app.md, PLAN.md § E13-T4/T8) — not paraphrased.

use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Listener, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogResult};

use crate::{daemon, status, windows};
use status::{DotState, Status};

#[path = "tray_menu.rs"]
mod tray_menu;
use tray_menu::build_menu_items;

#[path = "tray_click.rs"]
mod tray_click;

#[path = "tray_icon.rs"]
mod tray_icon;
use tray_icon::load_icon;

const QUIT_DIALOG_TEXT: &str =
    "Polling stops when Find+ quits. Install the background service so it keeps running?";
const SIGN_IN_URL: &str = "https://github.com/acamarata/findplus/wiki/Google-Sign-In";

static LAST_STATUS: OnceLock<Mutex<Status>> = OnceLock::new();
static CHROME_MISSING: OnceLock<Mutex<bool>> = OnceLock::new();

fn initial_status() -> Status {
    Status {
        state: DotState::Down,
        line: "Starting…".to_string(),
        latest: None,
        tracked: 0,
        version: String::new(),
    }
}

fn last_status_cell() -> &'static Mutex<Status> {
    LAST_STATUS.get_or_init(|| Mutex::new(initial_status()))
}

fn chrome_missing() -> bool {
    *CHROME_MISSING
        .get_or_init(|| Mutex::new(false))
        .lock()
        .unwrap()
}

pub fn setup(app: &mut tauri::App) -> tauri::Result<()> {
    let initial = initial_status();
    let menu = build_menu_items(app.handle(), &initial, false)?;

    let tray = TrayIconBuilder::new()
        .icon(load_icon(app.handle(), &initial.state))
        .icon_as_template(true)
        .menu(&menu)
        // The menu now only shows on right click; a left click opens the
        // dashboard instead (handle_tray_icon_event below). Right click keeps
        // working from tray-icon's own default (menu_on_right_click), which
        // Tauri never exposes a setter for because it never needs turning off.
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| handle_menu_event(app, event.id().as_ref()))
        .on_tray_icon_event(handle_tray_icon_event)
        .build(app)?;

    wire_status_listeners(app, tray.id().clone());
    Ok(())
}

/// A left click (button-up) on the tray icon opens/focuses the dashboard;
/// every other click just falls through to tray-icon's own menu handling.
fn handle_tray_icon_event(tray: &tauri::tray::TrayIcon, event: TrayIconEvent) {
    if let TrayIconEvent::Click {
        button,
        button_state,
        ..
    } = event
    {
        if tray_click::opens_dashboard(button, button_state) {
            windows::open_main(tray.app_handle());
        }
    }
}

/// Rebuild the menu (and swap the icon) on every signal that changes what it
/// should show: a fresh /api/status snapshot, or the daemon supervisor
/// spotting a port squatter or a crash.
fn wire_status_listeners(app: &mut tauri::App, tray_id: tauri::tray::TrayIconId) {
    let app_handle = app.handle().clone();
    let id1 = tray_id.clone();
    app.listen("status-update", move |event| {
        if let Ok(s) = serde_json::from_str::<Status>(event.payload()) {
            *last_status_cell().lock().unwrap() = s;
            refresh_chrome_missing();
            let _ = build_menu(&app_handle, &id1, &effective_status());
        }
    });

    let app_handle = app.handle().clone();
    let id2 = tray_id.clone();
    app.listen("daemon-another-app", move |_event| {
        let _ = build_menu(&app_handle, &id2, &effective_status());
    });

    let app_handle = app.handle().clone();
    app.listen("daemon-crashed", move |_event| {
        let _ = build_menu(&app_handle, &tray_id, &effective_status());
    });
}

/// The status the menu should actually show: the daemon supervisor's own
/// signals (another app on the port) take priority over the last polled
/// /api/status snapshot, since they are more specific.
fn effective_status() -> Status {
    let base = last_status_cell().lock().unwrap().clone();
    if let Some(line) = daemon::another_app_line() {
        return Status {
            state: DotState::Down,
            line,
            latest: None,
            tracked: base.tracked,
            version: base.version,
        };
    }
    base
}

fn refresh_chrome_missing() {
    std::thread::spawn(|| {
        let missing = probe_chrome_missing();
        *CHROME_MISSING
            .get_or_init(|| Mutex::new(false))
            .lock()
            .unwrap() = missing;
    });
}

/// Derive "Chrome missing" client-side from GET /api/providers — the
/// google-find-hub entry is unavailable and its reason mentions Chrome.
/// The pinned response shape (api-contract.md § routes_providers.py) is
/// never modified; no chrome_missing field is added in Python.
fn probe_chrome_missing() -> bool {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    else {
        return false;
    };
    let url = format!("{}/api/providers", crate::daemon::daemon_base());
    let Ok(resp) = client.get(url).send() else {
        return false;
    };
    let Ok(list) = resp.json::<Vec<serde_json::Value>>() else {
        return false;
    };
    list.iter().any(|p| {
        p.get("name").and_then(|v| v.as_str()) == Some("google-find-hub")
            && p.get("available").and_then(|v| v.as_bool()) == Some(false)
            && p.get("reason")
                .and_then(|v| v.as_str())
                .map(|r| r.to_lowercase().contains("chrome"))
                .unwrap_or(false)
    })
}

/// Rebuild the menu and swap the tray icon on the MAIN thread. The callers
/// are `app.listen` handlers, which run on the event-loop's worker thread;
/// NSMenu/NSStatusItem must only be touched from the main thread, and doing
/// the menu swap and the icon swap in one main-thread hop also stops the two
/// racing against each other.
pub fn build_menu(
    app: &AppHandle,
    tray_id: &tauri::tray::TrayIconId,
    status: &Status,
) -> tauri::Result<()> {
    let app = app.clone();
    let tray_id = tray_id.clone();
    let status = status.clone();
    app.clone().run_on_main_thread(move || {
        if let Err(e) = apply_menu(&app, &tray_id, &status) {
            log::error!("tray: menu refresh failed: {e}");
        }
    })
}

fn apply_menu(
    app: &AppHandle,
    tray_id: &tauri::tray::TrayIconId,
    status: &Status,
) -> tauri::Result<()> {
    let Some(tray) = app.tray_by_id(tray_id) else {
        return Ok(());
    };
    let menu = build_menu_items(app, status, chrome_missing())?;
    tray.set_menu(Some(menu))?;
    // set_icon() replaces the NSImage, and the new image is not a template:
    // macOS then drew the black glyph as-is, invisible on a dark menu bar
    // (1.1.4). Re-mark it after every swap so macOS tints it.
    tray.set_icon(Some(load_icon(app, &status.state)))?;
    tray.set_icon_as_template(true)?;
    Ok(())
}

fn handle_menu_event(app: &AppHandle, id: &str) {
    match id {
        "poll_now" => {
            let app = app.clone();
            std::thread::spawn(move || {
                let url = format!("{}/api/poll-now", crate::daemon::daemon_base());
                let _ = reqwest::blocking::Client::new().post(url).send();
                let _ = app.emit("poll-now-triggered", ());
            });
        }
        "lock" => {
            std::thread::spawn(|| {
                let url = format!("{}/api/lock/lock", crate::daemon::daemon_base());
                let _ = reqwest::blocking::Client::new().post(url).send();
            });
        }
        "open_dashboard" => windows::open_main(app),
        "sign_in" => {
            let _ = std::process::Command::new("open").arg(SIGN_IN_URL).spawn();
        }
        "settings" => windows::open_settings(app),
        "open_app" => {
            windows::open_main(app);
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.set_focus();
            }
        }
        "restart_daemon" => {
            let app = app.clone();
            std::thread::spawn(move || daemon::restart(&app));
        }
        "quit" => handle_quit(app),
        _ => {}
    }
}

fn handle_quit(app: &AppHandle) {
    if !daemon::child_running() {
        std::process::exit(0);
    }

    app.dialog()
        .message(QUIT_DIALOG_TEXT)
        .title("Find+")
        .buttons(MessageDialogButtons::YesNoCancelCustom(
            "Install service".to_string(),
            "Quit anyway".to_string(),
            "Cancel".to_string(),
        ))
        .show_with_result(move |result| match result {
            MessageDialogResult::Yes => {
                // Exit only AFTER the install has run: exiting straight after
                // the spawn killed the installer before it could finish. Stop
                // our own sidecar first so the freshly installed LaunchAgent
                // can bind port 8647.
                std::thread::spawn(|| {
                    let _ = std::process::Command::new("findplus-daemon")
                        .args(["start", "--yes"])
                        .status();
                    daemon::stop_child();
                    std::process::exit(0);
                });
            }
            MessageDialogResult::No => {
                daemon::stop_child();
                std::process::exit(0);
            }
            _ => {}
        });
}

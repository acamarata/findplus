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

use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Listener, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogResult};

use crate::{daemon, status, windows};
use status::{DotState, Status};

#[path = "tray_menu.rs"]
mod tray_menu;
use tray_menu::build_menu_items;

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
    *CHROME_MISSING.get_or_init(|| Mutex::new(false)).lock().unwrap()
}

pub fn setup(app: &mut tauri::App) -> tauri::Result<()> {
    let initial = initial_status();
    let menu = build_menu_items(app.handle(), &initial, false)?;

    let tray = TrayIconBuilder::new()
        .icon(load_template_icon(app.handle()))
        .icon_as_template(true)
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| handle_menu_event(app, event.id().as_ref()))
        .build(app)?;

    let tray_id = tray.id().clone();

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
    let id3 = tray_id;
    app.listen("daemon-crashed", move |_event| {
        let _ = build_menu(&app_handle, &id3, &effective_status());
    });

    Ok(())
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
        *CHROME_MISSING.get_or_init(|| Mutex::new(false)).lock().unwrap() = missing;
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
    let Ok(resp) = client.get("http://127.0.0.1:8647/api/providers").send() else {
        return false;
    };
    let Ok(list) = resp.json::<Vec<serde_json::Value>>() else {
        return false;
    };
    list.iter().any(|p| {
        p.get("name").and_then(|v| v.as_str()) == Some("google-find-hub")
            && p.get("available").and_then(|v| v.as_bool()) == Some(false)
            && p
                .get("reason")
                .and_then(|v| v.as_str())
                .map(|r| r.to_lowercase().contains("chrome"))
                .unwrap_or(false)
    })
}

/// Rebuild the menu and swap the tray icon to the matching dot PNG.
pub fn build_menu(
    app: &AppHandle,
    tray_id: &tauri::tray::TrayIconId,
    status: &Status,
) -> tauri::Result<()> {
    let Some(tray) = app.tray_by_id(tray_id) else {
        return Ok(());
    };
    let menu = build_menu_items(app, status, chrome_missing())?;
    tray.set_menu(Some(menu))?;
    // Colour dots carry real colour; template mode would flatten them to a
    // monochrome mask, so it is off for every state after the first paint.
    tray.set_icon_as_template(false)?;
    tray.set_icon(Some(load_icon(app, &status.state)))?;
    Ok(())
}

fn handle_menu_event(app: &AppHandle, id: &str) {
    match id {
        "poll_now" => {
            let app = app.clone();
            std::thread::spawn(move || {
                let _ = reqwest::blocking::Client::new()
                    .post("http://127.0.0.1:8647/api/poll-now")
                    .send();
                let _ = app.emit("poll-now-triggered", ());
            });
        }
        "lock" => {
            std::thread::spawn(|| {
                let _ = reqwest::blocking::Client::new()
                    .post("http://127.0.0.1:8647/api/lock")
                    .send();
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
            std::thread::spawn(move || daemon::start(app));
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
                std::thread::spawn(|| {
                    let _ = std::process::Command::new("findplus-daemon")
                        .args(["start", "--yes"])
                        .status();
                });
                std::process::exit(0);
            }
            MessageDialogResult::No => {
                daemon::stop_child();
                std::process::exit(0);
            }
            _ => {}
        });
}

fn load_icon(app: &AppHandle, state: &DotState) -> tauri::image::Image<'static> {
    let name = match status::dot_color(state) {
        status::DotColor::Green => "dot-green.png",
        status::DotColor::Amber => "dot-amber.png",
        status::DotColor::Red => "dot-red.png",
        status::DotColor::Grey => "dot-grey.png",
    };
    load_icon_named(app, name)
}

/// The initial, monochrome tray icon: white so `iconAsTemplate` lets macOS
/// auto-invert it for dark/light menu bars, before the first status arrives.
fn load_template_icon(app: &AppHandle) -> tauri::image::Image<'static> {
    load_icon_named(app, "tray-template.png")
}

fn load_icon_named(app: &AppHandle, name: &str) -> tauri::image::Image<'static> {
    let candidates = [
        app.path()
            .resource_dir()
            .ok()
            .map(|d| d.join("icons").join(name)),
        Some(
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("icons")
                .join(name),
        ),
    ];
    for candidate in candidates.into_iter().flatten() {
        if let Ok(img) = tauri::image::Image::from_path(&candidate) {
            return img.to_owned();
        }
    }
    // Fallback: a 1x1 transparent pixel if the named PNG cannot be loaded.
    tauri::image::Image::new_owned(vec![0, 0, 0, 0], 1, 1)
}

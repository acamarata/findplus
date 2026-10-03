//! Tray menu actions: what each menu item does, and the Quit confirm flow.
//!
//! Purpose    : Split out of tray.rs (300-line cap). Item ids come from
//!              tray_menu.rs.
//! Constraints: The Quit dialog wording is normative (specs/desktop-app.md).
//!              No item opens a browser, Finder or Chrome: "Sign in" opens the
//!              dashboard's own sign-in settings, and the attention items open
//!              the in-app login (spec in-app-login.md §6).

use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogResult};

use crate::attention::{Need, Provider};
use crate::{daemon, signin_window, windows};

const QUIT_DIALOG_TEXT: &str =
    "Polling stops when Find+ quits. Install the background service so it keeps running?";

pub(super) fn handle_menu_event(app: &AppHandle, id: &str) {
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
        // Used to open the wiki in the default browser; the dashboard's own
        // sign-in card now does the whole job inside Find+.
        "sign_in" => windows::open_settings(app),
        "attn_google_signin" => signin_window::open_for(app, Provider::Google, Need::Signin),
        "attn_google_unlock" => signin_window::open_for(app, Provider::Google, Need::Unlock),
        "attn_apple_signin" => signin_window::open_for(app, Provider::Apple, Need::Signin),
        "settings" => windows::open_settings(app),
        "open_app" => {
            windows::open_main(app);
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.set_focus();
            }
        }
        "update_restart" => crate::updater::install_from_tray(app),
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

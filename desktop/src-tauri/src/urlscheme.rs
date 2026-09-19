//! findplus:// URL scheme handling.
//!
//! Purpose    : Route the four findplus:// deep links to their actions.
//! Inputs     : A URL string from tauri::RunEvent::Opened (wired in lib.rs).
//! Outputs    : Opens the main/settings window, triggers a poll, or logs.
//! Constraints: refresh-widget must never re-`open` the findplus:// scheme —
//!              RunEvent::Opened would re-deliver it straight back here.

use crate::windows;

pub fn handle(app: &tauri::AppHandle, url: &str) {
    match url {
        "findplus://open" => windows::open_main(app),
        "findplus://poll" => {
            std::thread::spawn(|| {
                let _ = reqwest::blocking::Client::new()
                    .post("http://127.0.0.1:8647/api/poll-now")
                    .send();
            });
        }
        "findplus://settings" => windows::open_settings(app),
        "findplus://refresh-widget" => {
            // The WidgetCenter reload helper ships in E16; this ticket only
            // logs. Never spawn `open findplus://…` here — the OS would
            // redeliver that same URL as another RunEvent::Opened, looping.
            log::debug!("urlscheme: refresh-widget requested (E16 wires the reload helper)");
        }
        other => log::debug!("urlscheme: unrecognised URL {other}"),
    }
}

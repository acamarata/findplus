//! findplus:// URL scheme handling.
//!
//! Purpose    : Route the four findplus:// deep links to their actions.
//! Inputs     : A URL string from tauri::RunEvent::Opened (wired in lib.rs).
//! Outputs    : Opens the main/settings window, triggers a poll, or logs.
//! Constraints: refresh-widget must never re-`open` the findplus:// scheme —
//!              RunEvent::Opened would re-deliver it straight back here. It
//!              runs the reload-widgets helper directly instead (E16).

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::windows;

/// Derive the reload-widgets helper path from the running app's own
/// executable: it ships alongside the app binary in Contents/MacOS
/// (embed-widget.sh copies it there before signing).
pub(crate) fn reload_widgets_path(exe: &Path) -> PathBuf {
    exe.parent()
        .map(|dir| dir.join("reload-widgets"))
        .unwrap_or_else(|| PathBuf::from("reload-widgets"))
}

/// Run the reload-widgets helper, best-effort: logs on failure, never
/// panics, never propagates an error up to the caller.
pub(crate) fn reload_widget_timelines(helper_path: &Path) {
    match Command::new(helper_path).status() {
        Ok(status) if status.success() => {
            log::debug!("urlscheme: reload-widgets ran successfully");
        }
        Ok(status) => {
            log::warn!("urlscheme: reload-widgets exited with {status}");
        }
        Err(err) => {
            log::warn!("urlscheme: could not run reload-widgets: {err}");
        }
    }
}

pub fn handle(app: &tauri::AppHandle, url: &str) {
    match url {
        "findplus://open" => windows::open_main(app),
        "findplus://poll" => {
            std::thread::spawn(|| {
                let url = format!("{}/api/poll-now", crate::daemon::daemon_base());
                let _ = reqwest::blocking::Client::new().post(url).send();
            });
        }
        "findplus://settings" => windows::open_settings(app),
        "findplus://refresh-widget" => {
            if let Ok(exe) = std::env::current_exe() {
                reload_widget_timelines(&reload_widgets_path(&exe));
            }
        }
        other => log::debug!("urlscheme: unrecognised URL {other}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reload_widgets_path_is_sibling_of_app_binary() {
        let exe = Path::new("/Applications/Find+.app/Contents/MacOS/Find+");
        let helper = reload_widgets_path(exe);
        assert_eq!(
            helper,
            PathBuf::from("/Applications/Find+.app/Contents/MacOS/reload-widgets")
        );
    }

    #[test]
    fn reload_widget_timelines_tolerates_missing_helper() {
        // Must not panic even when the helper does not exist.
        reload_widget_timelines(Path::new("/nonexistent/reload-widgets"));
    }
}

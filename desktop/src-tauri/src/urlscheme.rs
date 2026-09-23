//! findplus:// URL scheme handling.
//!
//! Purpose    : Route the five findplus:// deep links to their actions.
//! Inputs     : A URL string from tauri::RunEvent::Opened (wired in lib.rs).
//! Outputs    : Opens the main/settings/places window, triggers a poll, or logs.
//! Constraints: refresh-widget must never re-`open` the findplus:// scheme —
//!              RunEvent::Opened would re-deliver it straight back here. It
//!              runs the reload-widgets helper directly instead (E16). URL
//!              classification is split into a pure `classify()` so the
//!              routing table is testable without a live AppHandle (this
//!              crate has no mock-runtime harness for one).

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

/// The pure classification of a `findplus://` URL, before any side effect.
///
/// Kept separate from `handle()` so the routing table has a unit test that
/// needs no AppHandle: `windows::open_main`/`open_settings`/`open_places`
/// all require a live Tauri runtime this crate has no mock for.
#[derive(Debug, PartialEq, Eq)]
enum Action {
    OpenMain,
    OpenSettings,
    OpenPlaces,
    Poll,
    RefreshWidget,
    Unknown,
}

fn classify(url: &str) -> Action {
    match url {
        "findplus://open" => Action::OpenMain,
        "findplus://settings" => Action::OpenSettings,
        "findplus://places" => Action::OpenPlaces,
        "findplus://poll" => Action::Poll,
        "findplus://refresh-widget" => Action::RefreshWidget,
        _ => Action::Unknown,
    }
}

pub fn handle(app: &tauri::AppHandle, url: &str) {
    match classify(url) {
        Action::OpenMain => windows::open_main(app),
        Action::OpenSettings => windows::open_settings(app),
        Action::OpenPlaces => windows::open_places(app),
        Action::Poll => {
            std::thread::spawn(|| {
                let url = format!("{}/api/poll-now", crate::daemon::daemon_base());
                let _ = reqwest::blocking::Client::new().post(url).send();
            });
        }
        Action::RefreshWidget => {
            if let Ok(exe) = std::env::current_exe() {
                reload_widget_timelines(&reload_widgets_path(&exe));
            }
        }
        Action::Unknown => log::debug!("urlscheme: unrecognised URL {url}"),
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

    #[test]
    fn classify_routes_every_known_scheme() {
        assert_eq!(classify("findplus://open"), Action::OpenMain);
        assert_eq!(classify("findplus://settings"), Action::OpenSettings);
        assert_eq!(classify("findplus://places"), Action::OpenPlaces);
        assert_eq!(classify("findplus://poll"), Action::Poll);
        assert_eq!(classify("findplus://refresh-widget"), Action::RefreshWidget);
    }

    #[test]
    fn classify_falls_back_to_unknown() {
        assert_eq!(classify("findplus://bogus"), Action::Unknown);
        assert_eq!(classify("not-a-findplus-url"), Action::Unknown);
    }
}

//! Window management: the main dashboard window and the splash window are
//! created from Rust (tauri.conf.json's app.windows is empty).

use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

/// Pure: may a window be pointed at port 8647?
///
/// A window built for `http://127.0.0.1:8647/` carries the app's remote
/// capability (`capabilities/remote.json`: `core:default` plus the three
/// notification permissions) and the `window.__findplus_native` script. When
/// the supervisor has decided something OTHER than the Find+ daemon owns the
/// port (`DaemonState::AnotherApp`), handing that surface over means handing
/// it to a program we have not identified. CR-C-E8 minor.
pub fn may_attach(another_app_line: Option<&str>) -> bool {
    another_app_line.is_none()
}

/// The guard around every window that points at the daemon's port.
///
/// Refusing re-emits `daemon-another-app` so the tray redraws with the
/// supervisor's own "Port 8647 is used by another program" line, which is
/// the state the user needs to see instead of a window.
fn refuse_if_another_app(app: &AppHandle) -> bool {
    if may_attach(crate::daemon::another_app_line().as_deref()) {
        return false;
    }
    let _ = app.emit("daemon-another-app", ());
    true
}

pub fn open_main(app: &AppHandle) {
    if refuse_if_another_app(app) {
        return;
    }
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.set_focus();
        return;
    }
    let _ = WebviewWindowBuilder::new(
        app,
        "main",
        WebviewUrl::External("http://127.0.0.1:8647/".parse().unwrap()),
    )
    .title("Find+")
    .inner_size(1280.0, 820.0)
    .decorations(true)
    // Runs before any page script, including main.js. The only writer of the
    // flag every native-only branch gates on, so a plain browser tab pointed at
    // :8647 never sees it (R-P2-13).
    .initialization_script("window.__findplus_native = true;")
    .build();
}

pub fn open_settings(app: &AppHandle) {
    if refuse_if_another_app(app) {
        return;
    }
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.eval("window.location.hash = '#settings'");
        let _ = win.show();
        let _ = win.set_focus();
        return;
    }
    let _ = WebviewWindowBuilder::new(
        app,
        "main",
        WebviewUrl::External("http://127.0.0.1:8647/#settings".parse().unwrap()),
    )
    .title("Find+")
    .inner_size(1280.0, 820.0)
    .decorations(true)
    // Runs before any page script, including main.js. The only writer of the
    // flag every native-only branch gates on, so a plain browser tab pointed at
    // :8647 never sees it (R-P2-13).
    .initialization_script("window.__findplus_native = true;")
    .build();
}

pub fn open_splash(app: &AppHandle) {
    if app.get_webview_window("splash").is_some() {
        return;
    }
    let _ = WebviewWindowBuilder::new(app, "splash", WebviewUrl::App("index.html".into()))
        .inner_size(400.0, 300.0)
        .decorations(false)
        .always_on_top(true)
        .build();
}

/// Close the splash window, if one is open. A no-op otherwise.
///
/// Nothing closed it before P2: the splash stayed on top of everything until
/// the process ended. first_launch::start calls this once the daemon answers,
/// and deliberately does not call it when the daemon never does, so the
/// splash's own "Find+ could not start" state stays on screen.
pub fn close_splash(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("splash") {
        let _ = win.close();
    }
}

#[cfg(test)]
#[path = "windows_tests.rs"]
mod tests;

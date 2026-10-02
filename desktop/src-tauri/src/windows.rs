//! Window management: the main dashboard window and the splash window are
//! created from Rust (tauri.conf.json's app.windows is empty).

use tauri::webview::PageLoadEvent;
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};

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
    show_main_at(app, "");
}

pub fn open_settings(app: &AppHandle) {
    show_main_at(app, "settings");
}

pub fn open_places(app: &AppHandle) {
    show_main_at(app, "places");
}

/// Show the dashboard, on `#<hash>` when one is given (empty: stay where it is).
fn show_main_at(app: &AppHandle, hash: &str) {
    if refuse_if_another_app(app) {
        return;
    }
    // Someone asked for the dashboard: a splash still saying "Starting" is stale.
    close_splash(app);
    if let Some(win) = app.get_webview_window("main") {
        if !hash.is_empty() {
            let _ = win.eval(format!("window.location.hash = '#{hash}'"));
        }
        let _ = win.show();
        let _ = win.set_focus();
        return;
    }
    let url = if hash.is_empty() {
        DASHBOARD.to_string()
    } else {
        format!("{DASHBOARD}#{hash}")
    };
    // The app runs with ActivationPolicy::Accessory (no Dock icon), which
    // means a freshly created window is not guaranteed to come to the front
    // on its own; set_focus() calls through to activateIgnoringOtherApps on
    // macOS, so a brand-new window gets the same "come to front" treatment
    // as the show()+set_focus() path above for an existing one.
    if let Ok(win) = build_main(app, &url) {
        let _ = win.show();
        let _ = win.set_focus();
    }
}

const DASHBOARD: &str = "http://127.0.0.1:8647/";

/// The one place the dashboard window is built. Its page loads drive the
/// sign-in event buffer (signin_events.rs): events sent while a page is
/// loading are kept and sent again once it can hear them.
fn build_main(app: &AppHandle, url: &str) -> tauri::Result<tauri::WebviewWindow> {
    let parsed = url
        .parse()
        .map_err(|_| tauri::Error::InvalidWebviewUrl("dashboard"))?;
    let loaded = app.clone();
    let win = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(parsed))
        .title("Find+")
        .inner_size(1280.0, 820.0)
        .decorations(true)
        // Runs before any page script, including main.js. The only writer of the
        // flag every native-only branch gates on, so a plain browser tab pointed at
        // :8647 never sees it (R-P2-13).
        .initialization_script("window.__findplus_native = true;")
        .on_page_load(move |_, p| match p.event() {
            PageLoadEvent::Started => drop(crate::signin_events::page_loading()),
            PageLoadEvent::Finished => crate::signin_events::page_loaded(&loaded),
        })
        .build()?;
    win.on_window_event(|ev| {
        if let WindowEvent::Destroyed = ev {
            crate::signin_events::page_loading();
        }
    });
    Ok(win)
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

/// Switch the splash from "Starting..." to its "could not start" state. A no-op
/// when there is no splash. The page has no script of its own, so this flips
/// the three elements it already carries.
pub fn show_splash_error(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("splash") {
        let _ = win.eval(
            "document.getElementById('spinner').classList.add('hidden');\
             document.getElementById('status').textContent='Still starting Find+...';\
             document.getElementById('error').classList.remove('hidden');",
        );
    }
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

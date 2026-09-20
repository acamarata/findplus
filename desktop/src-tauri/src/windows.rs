//! Window management: the main dashboard window and the splash window are
//! created from Rust (tauri.conf.json's app.windows is empty).

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};

pub fn open_main(app: &AppHandle) {
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

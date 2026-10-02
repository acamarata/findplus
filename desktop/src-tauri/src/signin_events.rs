//! Events for the dashboard page that must not be lost while it loads.
//!
//! Purpose    : `signin-apple-sheet`, `auth-attention` and `signin-result`
//!              often fire right after Rust creates (or reloads) the `main`
//!              window, before the page has registered its listeners, so the
//!              page never hears them. While the page is not ready the last
//!              event of each kind is kept and sent again once it is.
//! Inputs     : `main`'s page loads (windows.rs), `webview_ready` from the
//!              page, and every buffered event (signin_window.rs, attention.rs).
//! Outputs    : `emit_to("main", ..)` now or after the page is ready.
//! Constraints: The buffer is pure and unit-tested. "Ready" comes from the
//!              page's `webview_ready` call, or SETTLE after a finished load
//!              (an older page that never calls it). A kept event older than
//!              MAX_AGE is dropped: a sheet must not pop up long after the ask.

use serde_json::Value;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};

/// The kinds kept for a page that is not ready yet.
pub const KEPT: [&str; 3] = ["signin-apple-sheet", "auth-attention", "signin-result"];
/// After a finished load, how long the page gets to register its listeners.
pub const SETTLE: Duration = Duration::from_millis(1500);
/// A kept event older than this is not worth replaying.
pub const MAX_AGE: Duration = Duration::from_secs(120);

/// Pure: the page's readiness and the kept events, oldest first.
#[derive(Debug, Default)]
pub struct Buffer {
    ready: bool,
    load: u64,
    kept: Vec<(String, Value, Instant)>,
}

impl Buffer {
    /// True: send it now. False: kept (replacing an older one of its kind).
    /// A kind that is not kept is always sent (the page polls for those).
    pub fn offer(&mut self, name: &str, payload: Value, now: Instant) -> bool {
        if self.ready || !KEPT.contains(&name) {
            return true;
        }
        self.kept.retain(|(n, _, _)| n != name);
        self.kept.push((name.to_string(), payload, now));
        false
    }

    /// The page started loading (or the window is gone): not ready. Returns
    /// this load's number, so a late settle timer cannot mark a newer load.
    pub fn loading(&mut self) -> u64 {
        self.ready = false;
        self.load += 1;
        self.load
    }

    /// The page is ready: everything kept and still fresh, oldest first.
    /// `load` is Some for the settle timer (ignored if a newer load started or
    /// the page already said it is ready), None for the page's own call.
    pub fn ready(&mut self, load: Option<u64>, now: Instant) -> Vec<(String, Value)> {
        if load.is_some_and(|l| l != self.load || self.ready) {
            return Vec::new();
        }
        self.ready = true;
        std::mem::take(&mut self.kept)
            .into_iter()
            .filter(|(_, _, at)| now.duration_since(*at) <= MAX_AGE)
            .map(|(n, p, _)| (n, p))
            .collect()
    }
}

static BUFFER: Mutex<Buffer> = Mutex::new(Buffer {
    ready: false,
    load: 0,
    kept: Vec::new(),
});

fn with<T>(f: impl FnOnce(&mut Buffer) -> T) -> T {
    f(&mut BUFFER.lock().unwrap_or_else(|e| e.into_inner()))
}

/// Send an event to `main`, or keep it until the page is ready.
pub fn send(app: &AppHandle, name: &str, payload: Value) {
    if with(|b| b.offer(name, payload.clone(), Instant::now())) {
        let _ = app.emit_to("main", name, payload);
    }
}

/// Keep an event that went out app-wide (the tray hears it) in case the page
/// was not ready to hear it too. Sends nothing itself.
pub fn keep(name: &str, payload: Value) {
    let _ = with(|b| b.offer(name, payload, Instant::now()));
}

/// `main` started loading a page, or closed.
pub fn page_loading() -> u64 {
    with(Buffer::loading)
}

/// `main` finished loading: replay after SETTLE unless the page said ready
/// already (it may call `webview_ready` before the load finishes).
pub fn page_loaded(app: &AppHandle) {
    let load = with(|b| b.load);
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(SETTLE);
        replay(&app, Some(load));
    });
}

fn replay(app: &AppHandle, load: Option<u64>) {
    for (name, payload) in with(|b| b.ready(load, Instant::now())) {
        let _ = app.emit_to("main", name.as_str(), payload);
    }
}

/// The dashboard page has registered its listeners (main window only).
#[tauri::command]
pub fn webview_ready(app: AppHandle, webview: tauri::Webview) -> Result<(), String> {
    if webview.label() != "main" {
        return Err("not_main_window".into());
    }
    replay(&app, None);
    Ok(())
}

#[cfg(test)]
#[path = "signin_events_tests.rs"]
mod tests;

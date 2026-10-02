//! In-app sign-in: closing the window from outside it.
//!
//! Purpose    : The dashboard card's Cancel, and a cancel the daemon recorded
//!              by any other path, must close the Google sign-in window. The
//!              card calls `close_signin_window`; the session thread also
//!              reads the daemon's progress and stops when it says cancelled.
//! Inputs     : `close_signin_window` from the main window only; the daemon's
//!              `phase` from GET .../native/progress (signin_http.rs).
//! Outputs    : A close request the session thread takes on its next tick (it
//!              then posts `closed`, wipes the store and destroys the window).
//! Constraints: The flag and the stop rule are pure and unit-tested; nothing
//!              here creates a window. A request made before a session exists
//!              is dropped when the next session starts (signin_window::open
//!              clears it once it owns the session).

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Manager};

use crate::signin_machine::{Mode, Phase};

static REQUESTED: AtomicBool = AtomicBool::new(false);

/// A fresh session: forget any close asked for before it.
pub fn clear() {
    REQUESTED.store(false, Ordering::SeqCst);
}

/// Ask the running session to close its window.
pub fn request() {
    REQUESTED.store(true, Ordering::SeqCst);
}

/// True once per request: the session thread consumes it.
pub fn take_request() -> bool {
    REQUESTED.swap(false, Ordering::SeqCst)
}

/// Pure: does the daemon's progress mean this window should close?
///
/// The daemon's progress is the one truth (contract §3.8). Only while the
/// person is on a Google page (waiting or unlock); a token or key exchange in
/// flight finishes on its own. "cancelled" is the card's Cancel (or any other
/// cancel). "idle", or a different flow, means the daemon no longer knows
/// this window's state (it restarted, or a newer sign-in replaced it): the
/// window can never finish. "success" while the unlock page is showing after
/// a sign-in is the same Cancel: the daemon keeps the sign-in and marks the
/// locations locked, so the window has nothing left to do. "error" is never
/// a stop on its own.
pub fn daemon_says_stop(phase: Phase, mode: Mode, daemon_phase: &str, same_flow: bool) -> bool {
    let gone = !same_flow || daemon_phase == "cancelled" || daemon_phase == "idle";
    match phase {
        Phase::Waiting => gone,
        Phase::Unlocking => gone || (mode == Mode::Signin && daemon_phase == "success"),
        _ => false,
    }
}

/// What `close_signin_window` did, for the card (it ignores the answer).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CloseResult {
    /// A session is running: it closes the window on its next tick.
    Closing,
    /// A window was left without a session: wiped and destroyed now.
    Destroyed,
    NotOpen,
}

impl CloseResult {
    pub fn wire(self) -> &'static str {
        match self {
            CloseResult::Closing => "closing",
            CloseResult::Destroyed => "closed",
            CloseResult::NotOpen => "not_open",
        }
    }
}

/// Pure: what a close does, from whether a session runs and a window exists.
pub fn plan(session_running: bool, window_exists: bool) -> CloseResult {
    match (session_running, window_exists) {
        (true, _) => CloseResult::Closing,
        (false, true) => CloseResult::Destroyed,
        (false, false) => CloseResult::NotOpen,
    }
}

/// Close the Google sign-in window from the dashboard (main window only).
/// The card has already posted .../native/cancel; this ends the window.
#[tauri::command]
pub fn close_signin_window(
    app: AppHandle,
    webview: tauri::Webview,
    provider: String,
) -> Result<String, String> {
    if webview.label() != "main" {
        return Err("not_main_window".into());
    }
    if provider != "google" {
        return Err("unsupported_provider".into());
    }
    let win = app.get_webview_window(crate::signin_window::LABEL);
    let done = plan(crate::signin_window::is_active(), win.is_some());
    match (done, win) {
        (CloseResult::Closing, _) => request(),
        (CloseResult::Destroyed, Some(w)) => {
            let _ = w.clear_all_browsing_data();
            let _ = w.destroy();
        }
        _ => {}
    }
    Ok(done.wire().into())
}

#[cfg(test)]
#[path = "signin_close_tests.rs"]
mod tests;

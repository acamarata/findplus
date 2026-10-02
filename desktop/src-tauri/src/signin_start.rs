//! In-app sign-in: start one session (state, window, then the loop).
//!
//! Purpose    : Get the single-use state (handed over by the dashboard card,
//!              which has the session cookie, or minted here for the tray and
//!              deep-link paths), open the window, tell the daemon, and hand
//!              over to signin_session.rs.
//! Constraints: A 401 from begin means the app is locked: show the dashboard
//!              (its lock screen) and open no window (contract §2). Runs on a
//!              worker thread.

use serde_json::Value;
use tauri::AppHandle;

use crate::signin_http::{parse_begin, Begin, Daemon};
use crate::signin_logic::Hosts;
use crate::signin_machine::Mode;
use crate::signin_session::Session;
use crate::signin_window as window;

const MSG_BAD_BEGIN: &str = "Find+ could not start the sign-in. Try again.";

/// Run one sign-in session to its end. Never panics on a daemon or window error.
pub fn run(app: &AppHandle, mode: Mode, handed: Option<Value>) {
    window::progress(app, mode, "starting", false);
    let base = crate::daemon::daemon_base();
    let daemon = Daemon {
        cookie: window::session_cookie(app, &base),
        base,
    };
    let hosts = window::hosts();
    let Some(begin) = obtain_begin(app, mode, &daemon, &hosts, handed) else {
        return;
    };
    let (tx, rx) = window::channel();
    let win = match window::build(app, mode, &hosts, tx) {
        Ok(w) => w,
        Err(e) => {
            log::warn!("signin: could not open the window: {e}");
            daemon.event(&begin.state, "failed", Some("load_failed"));
            return window::fail_early(app, mode, "Find+ could not open the sign-in window.");
        }
    };
    daemon.event(&begin.state, "opened", None);
    let mut session = Session::new(app, win, mode, daemon, begin, hosts);
    window::progress(app, mode, "waiting", false);
    session.run_loop(&rx);
}

/// The card's begin reply when it sent one, else a fresh begin from here.
fn obtain_begin(
    app: &AppHandle,
    mode: Mode,
    daemon: &Daemon,
    hosts: &Hosts,
    handed: Option<Value>,
) -> Option<Begin> {
    if let Some(v) = handed {
        let parsed = parse_begin(&v, hosts);
        if parsed.is_none() {
            window::fail_early(app, mode, MSG_BAD_BEGIN);
        }
        return parsed;
    }
    match daemon.begin(mode.wire(), hosts) {
        Ok(b) => Some(b),
        Err(e) => {
            window::fail_early(app, mode, &e.message);
            if e.status == 401 {
                window::focus_main(app);
            }
            None
        }
    }
}

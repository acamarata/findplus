//! In-app sign-in: debug-only self-test launch (driven by tests/signin_e2e.rs).
//!
//! Purpose    : `FINDPLUS_SIGNIN_SELFTEST=<case>` starts the fake server
//!              (signin_fake.rs), points both the sign-in window and the daemon
//!              client at it, opens the REAL sign-in window (WKWebView, no
//!              Chrome, no Google), prints the `signin-result` payload as one
//!              `SIGNIN-RESULT {json}` line and exits.
//! Cases      : ok (sign in + unlock), unlock (unlock-only, account page),
//!              reject (Google-style rejection page), cancel (window closed).
//! Constraints: Compiled only with `debug_assertions`. No tray, daemon,
//!              splash, single-instance plugin or dashboard window.

use std::sync::atomic::Ordering;
use std::time::Duration;
use tauri::{AppHandle, Listener, Manager};

use crate::signin_machine::Mode;
use crate::signin_window;

/// The case name, when the self-test was asked for.
pub fn requested() -> Option<String> {
    let case = std::env::var("FINDPLUS_SIGNIN_SELFTEST").ok()?;
    ["ok", "unlock", "reject", "cancel"]
        .contains(&case.as_str())
        .then_some(case)
}

/// Start the fake server, then the window. Exits the app with the result.
pub fn start(app: &AppHandle, case: &str) {
    let Some(base) = crate::signin_fake::start(case) else {
        println!("SIGNIN-RESULT {{\"outcome\":\"selftest_server_failed\"}}");
        return app.exit(3);
    };
    let port = base.rsplit(':').next().unwrap_or("0").to_string();
    // Single-threaded here (setup, before any reader of these): the daemon
    // client resolves its port once, on first use, from FINDPLUS_PORT.
    std::env::set_var("FINDPLUS_SIGNIN_TEST_BASE", &base);
    std::env::set_var("FINDPLUS_PORT", port);
    signin_window::SELFTEST.store(true, Ordering::SeqCst);
    let exit_app = app.clone();
    app.listen_any("signin-result", move |e| {
        println!("SIGNIN-RESULT {}", e.payload());
        exit_app.exit(0);
    });
    let mode = if case == "unlock" {
        Mode::Unlock
    } else {
        Mode::Signin
    };
    signin_window::open(app, mode);
    let watchdog = app.clone();
    let cancel = case == "cancel";
    std::thread::spawn(move || {
        if cancel {
            std::thread::sleep(Duration::from_secs(3));
            if let Some(w) = watchdog.get_webview_window(signin_window::LABEL) {
                let _ = w.close();
            }
        }
        std::thread::sleep(Duration::from_secs(45));
        println!("SIGNIN-RESULT {{\"outcome\":\"selftest_watchdog\"}}");
        watchdog.exit(4);
    });
}

//! The menu-bar app outlives its windows.
//!
//! Purpose    : Pin the v1.1.1 fix. v1.1.0 never handled
//!              `RunEvent::ExitRequested`, so once setup was finished the
//!              splash closed, no window was left, Tauri quit with code 0
//!              and the tray icon disappeared while the sidecar kept running.
//! Inputs     : src/lib.rs as text (the run loop is not unit-testable without
//!              a live event loop).
//! Constraints: Only the implicit last-window exit (`code: None`) may be
//!              prevented; an explicit exit code must still quit.

const LIB: &str = include_str!("../src/lib.rs");

#[test]
fn the_implicit_last_window_exit_is_prevented() {
    assert!(
        LIB.contains("RunEvent::ExitRequested { code: None, api, .. } => api.prevent_exit()"),
        "closing the last window must not quit the menu-bar app"
    );
}

#[test]
fn an_explicit_exit_code_is_not_swallowed() {
    assert!(
        !LIB.contains("RunEvent::ExitRequested { api, .. } => api.prevent_exit()"),
        "preventing every exit would make app.exit(n) a no-op"
    );
}

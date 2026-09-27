//! The menu-bar app outlives its windows, never shows a Dock icon, and
//! reopens its dashboard instead of doing nothing.
//!
//! Purpose    : Pin the v1.1.1 fix (`RunEvent::ExitRequested`) plus the P2.1
//!              menu-bar redesign: no Dock icon ever (Accessory activation
//!              policy + Info.plist's LSUIElement), and reactivating an
//!              already-running Find+ from the Dock/Spotlight/Finder opens
//!              the dashboard (`RunEvent::Reopen`) instead of silently doing
//!              nothing.
//! Inputs     : src/lib.rs and src-tauri/Info.plist as text (the run loop and
//!              the bundler's plist merge are not unit-testable without a
//!              live event loop / a built bundle).
//! Constraints: Only the implicit last-window exit (`code: None`) may be
//!              prevented; an explicit exit code must still quit.

const LIB: &str = include_str!("../src/lib.rs");
const INFO_PLIST: &str = include_str!("../Info.plist");

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

#[test]
fn the_activation_policy_is_set_to_accessory_at_startup() {
    assert!(
        LIB.contains("app.set_activation_policy(tauri::ActivationPolicy::Accessory)"),
        "Tauri's own default (Regular) would put a Dock icon back the \
         moment the event loop starts, overriding Info.plist's LSUIElement"
    );
}

#[test]
fn info_plist_declares_lsuielement_true() {
    assert!(
        INFO_PLIST.contains("<key>LSUIElement</key>") && INFO_PLIST.contains("<true/>"),
        "LSUIElement must be true for Find+ to launch without a Dock icon"
    );
}

#[test]
fn reopen_focuses_the_dashboard() {
    assert!(
        LIB.contains("RunEvent::Reopen { .. } => windows::open_main(app_handle)"),
        "reactivating an already-running accessory app from the Dock/\
         Spotlight/Finder has no window of its own to click back to, so \
         Reopen must open the dashboard rather than doing nothing"
    );
}

#[test]
fn a_second_launch_also_opens_the_dashboard_via_single_instance() {
    assert!(
        LIB.contains("windows::open_main(app);"),
        "the single-instance callback must open the dashboard too, in case \
         the OS launches a second process instead of sending Reopen"
    );
}

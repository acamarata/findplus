//! Pure decision logic for the tray icon's left-click behaviour.
//!
//! Purpose    : A left click on the tray icon opens/focuses the dashboard
//!              directly instead of showing the dropdown menu (tray.rs's
//!              setup turns `show_menu_on_left_click` off); a right click
//!              keeps showing the menu, which tray-icon's own default
//!              (`menu_on_right_click`, never disabled here) still handles
//!              without any code in this crate. This module is only the
//!              "was that the click that should open the dashboard?"
//!              decision, kept pure so it is unit-tested without a live
//!              NSStatusItem.
//! Inputs     : The button/state pair from a `TrayIconEvent::Click`.
//! Outputs    : bool -- true opens/focuses the dashboard.
//! Constraints: Fires on button-up, not button-down, so a press that turns
//!              into a drag off the icon (or a menu already opening under a
//!              right click) never also opens a window.

use tauri::tray::{MouseButton, MouseButtonState};

/// True when this left-click event should open/focus the dashboard: the
/// left button, released (button-up) over the tray icon.
pub fn opens_dashboard(button: MouseButton, state: MouseButtonState) -> bool {
    button == MouseButton::Left && state == MouseButtonState::Up
}

#[cfg(test)]
#[path = "tray_click_tests.rs"]
mod tests;

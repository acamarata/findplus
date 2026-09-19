//! Menu item construction for the tray dropdown.
//!
//! Purpose    : Build the ordered item list specs/desktop-app.md pins, kept
//!              in its own module so tray.rs (event wiring, icon loading)
//!              stays under the 300-line file cap.

use tauri::menu::{IconMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::AppHandle;

use crate::daemon;
use crate::status::{DotState, Status};

/// Build the menu in the order specs/desktop-app.md pins: dot line
/// (disabled) · Restart daemon (only when Down after a crash) · latest
/// (hidden when Locked/Down) · tracked count (disabled) · Poll Now · Lock ·
/// Open Dashboard or Sign in (when Chrome is missing) · Settings… ·
/// separator · Open App · Quit Find+.
pub fn build_menu_items(
    app: &AppHandle,
    status: &Status,
    chrome_missing: bool,
) -> tauri::Result<Menu<tauri::Wry>> {
    let dot = IconMenuItem::with_id(app, "dot_line", &status.line, false, None, None::<&str>)?;
    let mut items: Vec<Box<dyn tauri::menu::IsMenuItem<tauri::Wry>>> = vec![Box::new(dot)];

    let crashed = status.state == DotState::Down && daemon::down_reason_is_crashed();
    if crashed {
        items.push(Box::new(MenuItem::with_id(
            app,
            "restart_daemon",
            "Restart daemon",
            true,
            None::<&str>,
        )?));
    }

    let hide_latest = matches!(status.state, DotState::Locked | DotState::Down);
    if !hide_latest {
        if let Some(latest) = &status.latest {
            items.push(Box::new(MenuItem::with_id(
                app,
                "latest",
                format!("Latest: {latest}"),
                false,
                None::<&str>,
            )?));
        }
    }

    items.push(Box::new(MenuItem::with_id(
        app,
        "tracked",
        format!("Tracked devices: {}", status.tracked),
        false,
        None::<&str>,
    )?));

    let poll_enabled = matches!(status.state, DotState::Ok | DotState::Stale);
    items.push(Box::new(MenuItem::with_id(
        app,
        "poll_now",
        "Poll Now",
        poll_enabled,
        None::<&str>,
    )?));

    let lock_enabled = !matches!(status.state, DotState::Locked | DotState::Down);
    items.push(Box::new(MenuItem::with_id(
        app,
        "lock",
        "Lock",
        lock_enabled,
        None::<&str>,
    )?));

    if chrome_missing {
        items.push(Box::new(MenuItem::with_id(
            app,
            "sign_in",
            "Sign in",
            true,
            None::<&str>,
        )?));
    } else {
        items.push(Box::new(MenuItem::with_id(
            app,
            "open_dashboard",
            "Open Dashboard",
            true,
            None::<&str>,
        )?));
    }
    items.push(Box::new(MenuItem::with_id(
        app,
        "settings",
        "Settings…",
        true,
        None::<&str>,
    )?));
    items.push(Box::new(PredefinedMenuItem::separator(app)?));
    items.push(Box::new(MenuItem::with_id(
        app,
        "open_app",
        "Open App",
        true,
        None::<&str>,
    )?));
    items.push(Box::new(MenuItem::with_id(
        app,
        "quit",
        "Quit Find+",
        true,
        None::<&str>,
    )?));

    let refs: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
        items.iter().map(|i| i.as_ref()).collect();
    Menu::with_items(app, &refs)
}

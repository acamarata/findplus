//! Menu item construction for the tray dropdown.
//!
//! Purpose    : Build the ordered item list specs/desktop-app.md pins, kept
//!              in its own module so tray.rs (event wiring, icon loading)
//!              stays under the 300-line file cap.
//! Constraints: Every function stays under the 50-line cap (PRI hard rule 7),
//!              so the ordered list is assembled from one helper per group.

use tauri::menu::{IconMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::AppHandle;

use crate::daemon;
use crate::status::{DotState, Status};

type Item = Box<dyn tauri::menu::IsMenuItem<tauri::Wry>>;

fn entry(app: &AppHandle, id: &str, text: String, enabled: bool) -> tauri::Result<Item> {
    Ok(Box::new(MenuItem::with_id(
        app,
        id,
        text,
        enabled,
        None::<&str>,
    )?))
}

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
    let mut items: Vec<Item> = Vec::new();
    items.extend(status_items(app, status)?);
    items.extend(action_items(app, status, chrome_missing)?);
    items.push(Box::new(PredefinedMenuItem::separator(app)?));
    items.push(entry(app, "open_app", "Open App".into(), true)?);
    items.push(entry(app, "quit", "Quit Find+".into(), true)?);

    let refs: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
        items.iter().map(|i| i.as_ref()).collect();
    Menu::with_items(app, &refs)
}

/// The read-only block: dot line, the crash-only Restart item, the latest
/// observation (hidden, not disabled, while Locked or Down) and the count.
fn status_items(app: &AppHandle, status: &Status) -> tauri::Result<Vec<Item>> {
    let dot = IconMenuItem::with_id(app, "dot_line", &status.line, false, None, None::<&str>)?;
    let mut items: Vec<Item> = vec![Box::new(dot)];

    if status.state == DotState::Down && daemon::down_reason_is_crashed() {
        items.push(entry(app, "restart_daemon", "Restart daemon".into(), true)?);
    }

    let hide_latest = matches!(status.state, DotState::Locked | DotState::Down);
    if !hide_latest {
        if let Some(latest) = &status.latest {
            items.push(entry(app, "latest", format!("Latest: {latest}"), false)?);
        }
    }

    items.push(entry(
        app,
        "tracked",
        format!("Tracked devices: {}", status.tracked),
        false,
    )?);
    Ok(items)
}

/// The actionable block: Poll Now (only while polling can work), Lock (only
/// while there is something to lock), the dashboard entry, and Settings.
fn action_items(
    app: &AppHandle,
    status: &Status,
    chrome_missing: bool,
) -> tauri::Result<Vec<Item>> {
    let poll_enabled = matches!(status.state, DotState::Ok | DotState::Stale);
    let lock_enabled = !matches!(status.state, DotState::Locked | DotState::Down);
    let mut items: Vec<Item> = vec![
        entry(app, "poll_now", "Poll Now".into(), poll_enabled)?,
        entry(app, "lock", "Lock".into(), lock_enabled)?,
    ];
    if chrome_missing {
        items.push(entry(app, "sign_in", "Sign in".into(), true)?);
    } else {
        items.push(entry(app, "open_dashboard", "Open Dashboard".into(), true)?);
    }
    items.push(entry(app, "settings", "Settings…".into(), true)?);
    Ok(items)
}

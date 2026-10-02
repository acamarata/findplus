//! Menu item construction for the tray dropdown.
//!
//! Purpose    : Build the ordered item list specs/desktop-app.md pins, kept
//!              in its own module so tray.rs (event wiring, icon loading)
//!              stays under the 300-line file cap.
//! Constraints: Every function stays under the 50-line cap (PRI hard rule 7),
//!              so the ordered list is assembled from one helper per group.

use tauri::menu::{IconMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::AppHandle;

use crate::attention::{Attention, Need};
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

/// Build the menu in the order specs/desktop-app.md pins, under the
/// in-app-login attention items when a provider lost its sign-in: dot line
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
    items.extend(attention_items(app, &crate::attention::current())?);
    items.extend(status_items(app, status)?);
    items.extend(action_items(app, status, chrome_missing)?);
    items.push(Box::new(PredefinedMenuItem::separator(app)?));
    items.push(entry(app, "open_app", "Open App".into(), true)?);
    items.push(entry(app, "quit", "Quit Find+".into(), true)?);

    let refs: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
        items.iter().map(|i| i.as_ref()).collect();
    Menu::with_items(app, &refs)
}

/// Pure: the top items for providers that lost their sign-in (spec §6):
/// (menu id, label). Empty while every provider is healthy.
pub fn attention_entries(a: &Attention) -> Vec<(&'static str, &'static str)> {
    let mut out = Vec::new();
    match a.google {
        Some(Need::Signin) => out.push(("attn_google_signin", "Sign in to Google again…")),
        Some(Need::Unlock) => out.push(("attn_google_unlock", "Unlock Google locations…")),
        None => {}
    }
    if a.apple.is_some() {
        out.push(("attn_apple_signin", "Sign in to Apple again…"));
    }
    out
}

fn attention_items(app: &AppHandle, a: &Attention) -> tauri::Result<Vec<Item>> {
    let mut items = Vec::new();
    for (id, label) in attention_entries(a) {
        items.push(entry(app, id, label.to_string(), true)?);
    }
    if !items.is_empty() {
        items.push(Box::new(PredefinedMenuItem::separator(app)?));
    }
    Ok(items)
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

    // desktop-app.md § Status mapping pins a visible "CLI daemon vX" line when the
    // daemon and the app disagree. daemon.rs only log::warn!ed it, so Status.version
    // was carried all the way here and rendered nowhere (E1 CR-C, CF-10).
    if !status.version.is_empty() && status.version != daemon::APP_VERSION {
        items.push(entry(
            app,
            "version_mismatch",
            format!(
                "CLI daemon v{} (app is v{})",
                status.version,
                daemon::APP_VERSION
            ),
            false,
        )?);
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attention_items_follow_the_daemon() {
        assert!(attention_entries(&Attention::default()).is_empty());
        let a = Attention { google: Some(Need::Signin), apple: Some(Need::Signin) };
        let ids: Vec<_> = attention_entries(&a).into_iter().map(|e| e.0).collect();
        assert_eq!(ids, vec!["attn_google_signin", "attn_apple_signin"]);
        let a = Attention { google: Some(Need::Unlock), apple: None };
        assert_eq!(attention_entries(&a), vec![("attn_google_unlock", "Unlock Google locations…")]);
    }
}

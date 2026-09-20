//! Native-alert poller: drains GET /api/alerts/deliveries?since=&channel=native every
//! 15 s and posts each row through tauri-plugin-notification, showing a generic
//! title/body pair while the app is locked or notification detail is turned off.
//!
//! Purpose    : Deliver queued "native" alert_deliveries rows (E8-T4) as macOS notifications.
//! Inputs     : GET .../deliveries JSON rows ({id, text, body}); GET /api/lock/status; GET
//!              /api/settings's alerts.native_detail; a persisted cursor file.
//! Outputs    : OS notifications (generic or detailed); POST .../ack calls; notify-cursor.json.
//! Constraints: next_cursor/should_process/generic_pair are pure and unit-tested without
//!              network, matching status.rs's from_api/dot_color split. Every network
//!              helper fails CLOSED to the generic pair, never open to real content.

use serde::Deserialize;
use std::path::PathBuf;
use std::time::Duration;
use tauri::{Emitter, Manager};
use tauri_plugin_notification::{NotificationExt, PermissionState};

// Base URL: crate::daemon::daemon_base() (F14) -- no local constant duplicates it.
const GENERIC_TITLE: &str = "Find+ alert";
const GENERIC_BODY: &str = "Find+ alert — open Find+ to see details";
const POLL_SECONDS: u64 = 15;
const HTTP_TIMEOUT: Duration = Duration::from_secs(5);
const CURSOR_FILE: &str = "notify-cursor.json";

/// One row of GET /api/alerts/deliveries. `text` is the server-rendered first line
/// (subject + verb), `body` the place + observed/lag lines. Both are optional: the
/// source place_event can have been pruned by retention before the app polled.
#[derive(Debug, Clone, Deserialize)]
struct DeliveryRow {
    id: u64,
    text: Option<String>,
    body: Option<String>,
    status: Option<String>,
}

/// Only a "queued" row is an unshown alert. The route filters by channel and by the
/// `since` cursor but not by status, so every row this app has already shown is still
/// returned to a cursor that points before it -- and the cursor file is deliberately
/// re-derivable (read_cursor returns 0 on a missing or unparsable file), so a reset
/// would otherwise re-notify the entire native history at once. An absent key is
/// treated as queued, so an older daemon that omits the field still works.
fn is_queued(row: &DeliveryRow) -> bool {
    match row.status.as_deref() {
        None => true,
        Some(status) => status == "queued",
    }
}

/// True when the response should be processed at all: any HTTP success. A locked
/// dashboard (401) or a down daemon (no response) both skip the cycle silently, per
/// spec § 2 "Lock rule" -- neither is an error worth surfacing.
fn should_process(http_status: Option<u16>) -> bool {
    matches!(http_status, Some(200))
}

/// The cursor never regresses: the max of the current value and every row's id, or the
/// current value unchanged when the response was empty or unprocessed.
fn next_cursor(current: u64, rows: &[DeliveryRow]) -> u64 {
    rows.iter().map(|r| r.id).fold(current, u64::max)
}

/// Pure decision: given the two upstream flags, which title/body pair to show. Locked
/// wins outright (spec § 2 "Generic content"); an unreachable lock-status check is
/// treated as locked, because fetch_locked() fails closed.
fn generic_pair(locked: bool, native_detail_enabled: bool) -> Option<(&'static str, &'static str)> {
    if locked || !native_detail_enabled {
        Some((GENERIC_TITLE, GENERIC_BODY))
    } else {
        None
    }
}

/// The title/body actually shown for one row. Falls back to the generic pair when the
/// row carries no rendered text, so a pruned source event can never produce a blank
/// notification.
fn title_body(row: &DeliveryRow, pair: Option<(&str, &str)>) -> (String, String) {
    match (&row.text, pair) {
        (_, Some((t, b))) => (t.to_string(), b.to_string()),
        (Some(text), None) => (text.clone(), row.body.clone().unwrap_or_default()),
        (None, None) => (GENERIC_TITLE.to_string(), GENERIC_BODY.to_string()),
    }
}

fn cursor_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path().app_data_dir().ok().map(|d| d.join(CURSOR_FILE))
}

/// 0 on any missing, unreadable or unparsable path: a lost cursor re-shows a backlog,
/// which is the safe direction. Never panics.
fn read_cursor(app: &tauri::AppHandle) -> u64 {
    let Some(path) = cursor_path(app) else {
        return 0;
    };
    let Ok(raw) = std::fs::read_to_string(path) else {
        return 0;
    };
    serde_json::from_str::<serde_json::Value>(&raw)
        .ok()
        .and_then(|v| v.get("last_seen_id").and_then(|n| n.as_u64()))
        .unwrap_or(0)
}

/// Creates the parent directory and ignores every I/O error: the poller must never die
/// over a cursor it can re-derive.
fn write_cursor(app: &tauri::AppHandle, cursor: u64) {
    let Some(path) = cursor_path(app) else {
        return;
    };
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let body = serde_json::json!({ "last_seen_id": cursor }).to_string();
    let _ = std::fs::write(path, body);
}

fn fetch_deliveries(since: u64) -> (Option<u16>, Vec<DeliveryRow>) {
    fetch_deliveries_from(&crate::daemon::daemon_base(), since)
}

fn fetch_deliveries_from(base: &str, since: u64) -> (Option<u16>, Vec<DeliveryRow>) {
    let client = match reqwest::blocking::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
    {
        Ok(c) => c,
        Err(_) => return (None, Vec::new()),
    };
    let url = format!("{base}/api/alerts/deliveries?since={since}&channel=native");
    match client.get(url).send() {
        Ok(resp) if resp.status().as_u16() == 200 => {
            // A body that will not parse yields an empty Vec, never a panic.
            (Some(200), resp.json::<Vec<DeliveryRow>>().unwrap_or_default())
        }
        Ok(resp) => (Some(resp.status().as_u16()), Vec::new()),
        Err(_) => (None, Vec::new()),
    }
}

fn ack(id: u64) {
    ack_at(&crate::daemon::daemon_base(), id);
}

/// Fire and forget: a failed ack simply re-delivers next cycle, so it must never
/// propagate.
fn ack_at(base: &str, id: u64) {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
    else {
        return;
    };
    let _ = client
        .post(format!("{base}/api/alerts/deliveries/{id}/ack"))
        .send();
}

fn fetch_locked() -> bool {
    fetch_locked_from(&crate::daemon::daemon_base())
}

/// EVERY failure path (unreachable, non-200, unparseable body, key absent) returns
/// true: fail closed to the generic notification, never open to real content.
fn fetch_locked_from(base: &str) -> bool {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
    else {
        return true;
    };
    let Ok(resp) = client.get(format!("{base}/api/lock/status")).send() else {
        return true;
    };
    if resp.status().as_u16() != 200 {
        return true;
    }
    let Ok(body) = resp.json::<serde_json::Value>() else {
        return true;
    };
    body.get("locked").and_then(|v| v.as_bool()).unwrap_or(true)
}

fn fetch_native_detail_enabled() -> bool {
    fetch_native_detail_enabled_from(&crate::daemon::daemon_base())
}

/// Only called when fetch_locked() is false (locked already forces generic). EVERY
/// failure path returns false: fail closed to generic.
fn fetch_native_detail_enabled_from(base: &str) -> bool {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
    else {
        return false;
    };
    let Ok(resp) = client.get(format!("{base}/api/settings")).send() else {
        return false;
    };
    if resp.status().as_u16() != 200 {
        return false;
    }
    let Ok(body) = resp.json::<serde_json::Value>() else {
        return false;
    };
    body.get("alerts.native_detail")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

/// Show one cycle's rows, ack each of them, and return nothing. A denied OS permission
/// still acks (Find+ never re-shows the same alert) and emits the tray's existing
/// "status-update" event rather than inventing a second channel.
fn show_cycle(app: &tauri::AppHandle, rows: &[DeliveryRow]) {
    // Checked once per cycle, only when there is something to show.
    let locked = fetch_locked();
    let native_detail_enabled = if locked {
        false
    } else {
        fetch_native_detail_enabled()
    };
    let pair = generic_pair(locked, native_detail_enabled);
    // Ruling R-P2-9: the poller NEVER prompts. It only reads the current state before
    // every .show(), re-read each loop since System Settings can change it.
    let granted = app
        .notification()
        .permission_state()
        .map(|s| s == PermissionState::Granted)
        .unwrap_or(false);
    // Emitted at most once per cycle, not once per row: a blocked permission with a
    // backlog of twenty rows is one tray state, not twenty events.
    let mut blocked_reported = false;
    for row in rows.iter().filter(|r| is_queued(r)) {
        if granted {
            let (title, body) = title_body(row, pair);
            let _ = app.notification().builder().title(title).body(body).show();
        } else if !blocked_reported {
            let _ = app.emit("status-update", serde_json::json!({"notify_blocked": true}));
            blocked_reported = true;
        }
        ack(row.id);
    }
}

/// Poll every 15 s (D-P2-9); post each queued native delivery, ack it, advance the cursor.
pub fn start(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let mut cursor = read_cursor(&app);
        loop {
            let (http_status, rows) = fetch_deliveries(cursor);
            if should_process(http_status) {
                if !rows.is_empty() {
                    show_cycle(&app, &rows);
                }
                cursor = next_cursor(cursor, &rows);
                write_cursor(&app, cursor);
            }
            std::thread::sleep(Duration::from_secs(POLL_SECONDS));
        }
    });
}

/// Ruling R-P2-9: the ONLY place Find+ raises the OS notification prompt. It is invoked
/// from the onboarding wizard's "Enable notifications" button (a user gesture), never by
/// the poller and never at startup. Returns the resulting state so the button can report
/// it; already-granted is a no-op.
#[tauri::command]
pub fn request_notification_permission(app: tauri::AppHandle) -> Result<String, String> {
    let state = app
        .notification()
        .permission_state()
        .map_err(|e| e.to_string())?;
    if state == PermissionState::Granted {
        return Ok("granted".to_string());
    }
    app.notification()
        .request_permission()
        .map(|s| format!("{s:?}").to_lowercase())
        .map_err(|e| e.to_string())
}

#[cfg(test)]
#[path = "notify_tests.rs"]
mod tests;

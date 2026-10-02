//! Status poller: reads GET /api/status every 45 s and maps it onto the
//! tray's Status/DotState per specs/desktop-app.md § Status mapping.
//!
//! Purpose    : Single source of truth for what the tray icon shows (the
//!              "F+" glyph, full-opacity or greyed) and what its status
//!              line says.
//! Inputs     : /api/status JSON (or a 401 body, treated as locked).
//! Outputs    : Status, emitted as a "status-update" event to every window.
//! Constraints: from_api/tray_icon_state are pure and unit-tested without
//!              network.

use serde_json::Value;
use std::time::Duration;
use tauri::Emitter;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DotState {
    Ok,
    Stale,
    Error,
    Locked,
    Down,
}

/// The tray icon's only two visual states, since the P2.1 menu-bar redesign
/// replaced the five-colour dot set with one "F+" glyph template image:
/// Normal is full opacity, Greyed is the same glyph at ~38% alpha. The
/// colour information the old dot icons carried now lives only in the
/// menu's disabled status-line text (tray_menu.rs's "dot_line" item).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrayIconState {
    Normal,
    Greyed,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Status {
    pub state: DotState,
    pub line: String,
    pub latest: Option<String>,
    pub tracked: u32,
    pub version: String,
}

/// Normal only while healthy and polling (Ok); everything else -- starting
/// up, nothing signed in, stale data, locked, or erroring -- is Greyed.
pub fn tray_icon_state(s: &DotState) -> TrayIconState {
    match s {
        DotState::Ok => TrayIconState::Normal,
        DotState::Stale | DotState::Error | DotState::Locked | DotState::Down => {
            TrayIconState::Greyed
        }
    }
}

/// Map a /api/status JSON body (or a synthetic `{"http_status": 401}` /
/// `{"http_status": 0}` marker the caller constructs for a failed probe)
/// onto Status, per specs/desktop-app.md § Status mapping, in priority
/// order: Down, Locked, Error, Stale, Ok. Each priority tier is its own
/// classifier below (loop2 C1 — from_api() used to be one 76-line function);
/// from_api() itself is just the dispatch in that priority order.
pub fn from_api(json: &Value, interval_min: u64) -> Status {
    let version = json
        .get("version")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let tracked = json
        .get("tracked_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;

    down_or_locked(json, tracked, &version)
        .or_else(|| error_status(json, tracked, &version))
        .or_else(|| stale_status(json, interval_min, tracked, &version))
        .unwrap_or_else(|| ok_status(json, tracked, &version))
}

/// Down (probe failed entirely) or Locked (401) — the two states that never
/// look at the rest of the body.
fn down_or_locked(json: &Value, tracked: u32, version: &str) -> Option<Status> {
    match json.get("http_status").and_then(|v| v.as_i64()) {
        Some(0) => Some(Status {
            state: DotState::Down,
            line: "Find+ is not running".to_string(),
            latest: None,
            tracked,
            version: version.to_string(),
        }),
        Some(401) => Some(Status {
            state: DotState::Locked,
            line: "Locked".to_string(),
            latest: None,
            tracked,
            version: version.to_string(),
        }),
        _ => None,
    }
}

/// Error: an auth/decrypt failure, or 3+ consecutive failed polls.
fn error_status(json: &Value, tracked: u32, version: &str) -> Option<Status> {
    let last_error_type = json.get("last_error_type").and_then(|v| v.as_str());
    let consecutive_failures = json
        .get("consecutive_failures")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    if !(matches!(last_error_type, Some("auth") | Some("decrypt")) || consecutive_failures >= 3) {
        return None;
    }
    let line = match last_error_type {
        Some("auth") => "Sign-in needed".to_string(),
        Some("decrypt") => "Decryption error".to_string(),
        _ => format!("{consecutive_failures} failed polls"),
    };
    Some(Status {
        state: DotState::Error,
        line,
        latest: latest_line(json),
        tracked,
        version: version.to_string(),
    })
}

/// Stale: the last poll is more than 2x the daemon's own interval old.
fn stale_status(json: &Value, interval_min: u64, tracked: u32, version: &str) -> Option<Status> {
    let last_poll_at = json.get("last_poll_at").and_then(|v| v.as_str());
    if !is_stale(last_poll_at, interval_min) {
        return None;
    }
    Some(Status {
        state: DotState::Stale,
        line: format!("Last poll {} ago", age_string(last_poll_at)),
        latest: latest_line(json),
        tracked,
        version: version.to_string(),
    })
}

/// Ok: the fallback when none of the above tiers matched.
fn ok_status(json: &Value, tracked: u32, version: &str) -> Status {
    let last_poll_at = json.get("last_poll_at").and_then(|v| v.as_str());
    Status {
        state: DotState::Ok,
        line: format!(
            "Polling normally · last poll {} ago{}",
            age_string(last_poll_at),
            next_poll_suffix(json)
        ),
        latest: latest_line(json),
        tracked,
        version: version.to_string(),
    }
}

// As built by E8 (cli/src/findplus/api/routes_core.py), /api/status has no
// flat "latest" string: it carries "latest_observation" (device_name,
// latitude, longitude, age_seconds; no place name in this payload) or
// "devices"/"latest_observation" per device. Build the spec's
// "<device>: seen <age> ago near <lat,lon>" line from that object.
fn latest_line(json: &Value) -> Option<String> {
    let obs = json.get("latest_observation")?;
    if obs.is_null() {
        return None;
    }
    let name = obs
        .get("device_name")
        .and_then(|v| v.as_str())
        .unwrap_or("Device");
    let age = obs
        .get("age_seconds")
        .and_then(|v| v.as_f64())
        .map(|s| age_from_seconds(s as i64))
        .unwrap_or_else(|| "unknown".to_string());
    let lat = obs.get("latitude").and_then(|v| v.as_f64());
    let lon = obs.get("longitude").and_then(|v| v.as_f64());
    let place = match (lat, lon) {
        (Some(a), Some(b)) => format!("{a:.3},{b:.3}"),
        _ => "an unknown location".to_string(),
    };
    Some(format!("{name}: seen {age} ago near {place}"))
}

/// The spec's Ok line ends "· next in 3 min", from /api/status's
/// `next_poll_at`; empty when the daemon reports none (never polled, poller
/// off) rather than inventing a time.
fn next_poll_suffix(json: &Value) -> String {
    let Some(ts) = json
        .get("next_poll_at")
        .and_then(|v| v.as_str())
        .and_then(parse_iso)
    else {
        return String::new();
    };
    let remaining = ts - now_epoch();
    if remaining <= 0 {
        return " · next poll due".to_string();
    }
    format!(" · next in {} min", remaining.div_euclid(60) + 1)
}

/// Poll /api/status every 45 s and emit "status-update" to every window.
///
/// Also pushes a WidgetKit timeline reload (via the reload-widgets helper,
/// E16) whenever `last_poll_at` changes, so the widget follows the daemon's
/// poll cadence rather than waiting on WidgetKit's own ~15-minute budget.
pub fn start(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let mut prev_last_poll_at: Option<String> = None;
        loop {
            let json = fetch_status();
            // Stale = 2 x the daemon's OWN interval (specs/desktop-app.md
            // § Status mapping); 5 is only a fallback for an older payload.
            let interval = json
                .get("poll_interval_minutes")
                .and_then(|v| v.as_u64())
                .filter(|v| *v > 0)
                .unwrap_or(5);
            let status = from_api(&json, interval);
            let _ = app.emit("status-update", &status);
            // Lost sign-in: tray item, one banner, deep-link gate (spec §6).
            crate::attention::refresh(&app);

            let last_poll_at = json
                .get("last_poll_at")
                .and_then(|v| v.as_str())
                .map(String::from);
            if last_poll_at.is_some() && last_poll_at != prev_last_poll_at {
                if let Ok(exe) = std::env::current_exe() {
                    let helper = crate::urlscheme::reload_widgets_path(&exe);
                    crate::urlscheme::reload_widget_timelines(&helper);
                }
                prev_last_poll_at = last_poll_at;
            }

            std::thread::sleep(Duration::from_secs(45));
        }
    });
}

fn fetch_status() -> Value {
    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return serde_json::json!({"http_status": 0}),
    };
    let url = format!("{}/api/status", crate::daemon::daemon_base());
    match client.get(url).send() {
        Ok(resp) if resp.status().as_u16() == 401 => serde_json::json!({"http_status": 401}),
        Ok(resp) if resp.status().is_success() => resp
            .json::<Value>()
            .unwrap_or_else(|_| serde_json::json!({"http_status": 0})),
        _ => serde_json::json!({"http_status": 0}),
    }
}

#[path = "status_age.rs"]
mod age;
use age::{age_from_seconds, age_string, is_stale, now_epoch, parse_iso};

#[cfg(test)]
#[path = "status_tests.rs"]
mod tests;

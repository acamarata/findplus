//! First-launch window decision: opens the dashboard once while onboarding is
//! incomplete, then stays tray-only.
//!
//! Purpose    : Someone who has just installed Find+ should see the setup
//!              wizard, not an empty tray icon; someone who finished it should
//!              not have a window pushed at them on every launch.
//! Inputs     : GET /api/health, then GET /api/settings, on the loopback daemon.
//! Outputs    : closes the splash window; opens the main window iff decide().
//! Constraints: decide() is pure, like status::from_api, so every branch is
//!              unit-tested without a daemon. Anything other than a clean 200
//!              saying onboarding is unfinished stays tray-only: never
//!              surprise-open a window on a half-healthy daemon.

use serde_json::Value;
use std::time::{Duration, Instant};
use tauri::AppHandle;

/// How long to wait for the daemon, and how often to ask.
const HEALTH_BUDGET: Duration = Duration::from_secs(30);
const HEALTH_INTERVAL: Duration = Duration::from_millis(500);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(2);

/// The wire key is dotted (ruling F6) and the settings body is flat, so this
/// is one map lookup, never a nested path.
const COMPLETED_AT: &str = "onboarding.completed_at";

/// Pure: true = open the main window. specs/onboarding.md § 7's four branches,
/// in priority order.
pub fn decide(settings_json: &Value, http_status: Option<i64>) -> bool {
    if http_status == Some(401) {
        // Locked. A PIN exists, which implies a wizard that already ran; a
        // window forced over a lock screen is worse than staying tray-only.
        return false;
    }
    if http_status != Some(200) {
        // Timeout, non-200, malformed body: fail safe.
        return false;
    }
    let completed = settings_json.get(COMPLETED_AT);
    // A payload from before this field existed cannot mean "definitely
    // finished", so a missing key counts as never onboarded.
    matches!(completed, Some(Value::Null)) || completed.is_none()
}

/// Poll health until the daemon answers, read the settings once, then decide.
///
/// If the daemon never becomes healthy inside the budget, the splash keeps
/// showing its own error state: close_splash is deliberately never called.
pub fn start(app: AppHandle) {
    std::thread::spawn(move || {
        let Ok(client) = reqwest::blocking::Client::builder()
            .timeout(REQUEST_TIMEOUT)
            .build()
        else {
            return;
        };
        let base = crate::daemon::daemon_base();
        let deadline = Instant::now() + HEALTH_BUDGET;
        loop {
            if client
                .get(format!("{base}/api/health"))
                .send()
                .map(|r| r.status().is_success())
                .unwrap_or(false)
            {
                break;
            }
            if Instant::now() >= deadline {
                return;
            }
            std::thread::sleep(HEALTH_INTERVAL);
        }

        let (settings_json, http_status) = match client.get(format!("{base}/api/settings")).send() {
            Ok(resp) => {
                let status = resp.status().as_u16() as i64;
                (resp.json::<Value>().unwrap_or(Value::Null), Some(status))
            }
            Err(_) => (Value::Null, None),
        };
        crate::windows::close_splash(&app);
        if decide(&settings_json, http_status) {
            crate::windows::open_main(&app);
        }
    });
}

#[cfg(test)]
#[path = "first_launch_tests.rs"]
mod tests;

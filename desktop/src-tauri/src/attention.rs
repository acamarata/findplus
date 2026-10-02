//! Lost sign-in ("attention"): which provider needs the person, and what
//! the app does about it (spec §6).
//!
//! Purpose    : Read `GET /api/auth/status` on the status loop, keep the last
//!              answer, rebuild the tray when it changes, post ONE generic
//!              native banner when a provider newly needs attention, and gate
//!              the sign-in deep links on it.
//! Inputs     : `/api/auth/status` (`providers[].attention`: "reauth",
//!              "unlock" or "none"; an older daemon without it falls back to
//!              `needs` containing "reauth" or "shared_key").
//! Outputs    : `auth-attention` event; a notification; `current()`.
//! Constraints: Banner text names no account and no place (generic-while-
//!              locked rule, notify.rs). The notification plugin cannot report
//!              a click on desktop, so the text points to the menu bar icon.
//!              `parse`, `banner` and `gate` are pure; which loss already had
//!              its banner is kept across app starts (attention_memory.rs).

use serde_json::Value;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use tauri_plugin_notification::{NotificationExt, PermissionState};

use crate::attention_memory as memory;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Need {
    Signin,
    Unlock,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provider {
    Google,
    Apple,
}

/// The per-provider attention the app last read. `None` = healthy.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, serde::Serialize)]
pub struct Attention {
    pub google: Option<Need>,
    pub apple: Option<Need>,
}

impl Attention {
    pub fn get(&self, p: Provider) -> Option<Need> {
        match p {
            Provider::Google => self.google,
            Provider::Apple => self.apple,
        }
    }
}

fn need_of(p: &Value) -> Option<Need> {
    match p.get("attention").and_then(Value::as_str) {
        Some("reauth" | "signin") => return Some(Need::Signin),
        Some("unlock") => return Some(Need::Unlock),
        Some(_) => return None,
        None if p.get("attention").is_some() => return None,
        None => {}
    }
    // Older daemon without `attention`: derive it from `needs`.
    let needs: Vec<&str> = p
        .get("needs")
        .and_then(Value::as_array)
        .map_or(Vec::new(), |a| a.iter().filter_map(Value::as_str).collect());
    if needs.contains(&"reauth") {
        Some(Need::Signin)
    } else if needs.contains(&"shared_key") {
        Some(Need::Unlock)
    } else {
        None
    }
}

/// Pure: the attention in one `/api/auth/status` body. None if it is not one.
pub fn parse(body: &Value) -> Option<Attention> {
    let providers = body.get("providers")?.as_array()?;
    let mut a = Attention::default();
    for p in providers {
        match p.get("id").and_then(Value::as_str) {
            Some("google-find-hub") => a.google = need_of(p),
            Some("apple-find-my") => a.apple = need_of(p),
            _ => {}
        }
    }
    Some(a)
}

/// Pure: the banner for one loss. Generic: no account, no place.
pub fn banner(p: Provider, n: Need) -> (&'static str, &'static str) {
    let body = match (p, n) {
        (Provider::Google, Need::Signin) => {
            "Google signed Find+ out. Click the Find+ menu bar icon to sign in again."
        }
        (Provider::Google, Need::Unlock) => {
            "Google locations are locked again. Click the Find+ menu bar icon to unlock them."
        }
        (Provider::Apple, _) => {
            "Apple signed Find+ out. Click the Find+ menu bar icon to sign in again."
        }
    };
    ("Find+ needs you", body)
}

/// What a sign-in deep link may do. Any web page can fire `findplus://`, so it
/// opens the login only while that provider actually needs it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Gate {
    Open(Need),
    Settings,
}

/// Pure: the gate for one deep link (contract §4). It opens only the login
/// it names, only while that provider needs exactly that, and never while
/// the app is locked. Apple has one link for any attention.
pub fn gate(provider: Provider, link: Need, current: Option<Need>, locked: bool) -> Gate {
    match current {
        _ if locked => Gate::Settings,
        Some(n) if n == link || provider == Provider::Apple => Gate::Open(n),
        _ => Gate::Settings,
    }
}

static CURRENT: Mutex<Attention> = Mutex::new(Attention {
    google: None,
    apple: None,
});

/// True while /api/auth/status answers 401 (the app lock is on).
static LOCKED: AtomicBool = AtomicBool::new(false);

/// Whether the last read found the app locked.
pub fn locked() -> bool {
    LOCKED.load(Ordering::SeqCst)
}

/// The last attention read from the daemon.
pub fn current() -> Attention {
    *CURRENT.lock().unwrap_or_else(|e| e.into_inner())
}

fn fetch() -> Option<Attention> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .ok()?;
    let resp = client
        .get(format!("{}/api/auth/status", crate::daemon::daemon_base()))
        .send()
        .ok()?;
    LOCKED.store(resp.status().as_u16() == 401, Ordering::SeqCst);
    if !resp.status().is_success() {
        // Locked (401) or down: keep what we knew.
        return None;
    }
    parse(&resp.json::<Value>().ok()?)
}

/// Read the daemon once and act on a change. Called from the status loop.
pub fn refresh(app: &AppHandle) {
    let Some(next) = fetch() else { return };
    let prev = std::mem::replace(
        &mut *CURRENT.lock().unwrap_or_else(|e| e.into_inner()),
        next,
    );
    announce(app, &next);
    if prev == next {
        return;
    }
    let _ = app.emit("auth-attention", next);
    // The tray heard it; a dashboard page still loading did not.
    if let Ok(v) = serde_json::to_value(next) {
        crate::signin_events::keep("auth-attention", v);
    }
}

/// One banner per loss, remembered across app starts (attention_memory.rs).
fn announce(app: &AppHandle, next: &Attention) {
    let file = memory::path();
    let notified = file.as_deref().map(memory::load).unwrap_or_default();
    let (banners, keep) = memory::due(notified, next);
    if keep != notified {
        if let Some(f) = &file {
            memory::save(f, keep);
        }
    }
    for (p, n) in banners {
        show_banner(app, p, n);
    }
}

/// Re-read soon after a sign-in window closes, so the tray item goes away.
pub fn refresh_soon(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_secs(2));
        refresh(&app);
    });
}

fn show_banner(app: &AppHandle, p: Provider, n: Need) {
    let granted = app
        .notification()
        .permission_state()
        .map(|s| s == PermissionState::Granted);
    if !granted.unwrap_or(false) {
        return;
    }
    let (title, body) = banner(p, n);
    let _ = app.notification().builder().title(title).body(body).show();
}

#[cfg(test)]
#[path = "attention_tests.rs"]
mod tests;

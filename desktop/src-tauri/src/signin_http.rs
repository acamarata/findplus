//! In-app sign-in: the loopback calls to the daemon's native sign-in routes.
//!
//! Purpose    : begin (mint the single-use state), token (hand over the
//!              oauth_token), unlock (hand over the vault keys), event and
//!              classify (tell the daemon what the window saw). Contract:
//!              .github/docs/specs/in-app-login-contract.md §2, §3.
//! Inputs     : The daemon base URL and, when the dashboard is unlocked behind
//!              a PIN, its session cookie read from the main window.
//! Outputs    : Parsed replies, or an `ApiError` whose message is safe to show.
//! Constraints: Blocking reqwest; call only from a worker thread. Every post
//!              carries the daemon's own Origin and `X-FindPlus-Client:
//!              signin-window`. The token and the vault keys are moved into
//!              one request body each and never formatted, logged or put in
//!              an error. Parsing and messages are pure and unit-tested.

use serde_json::{json, Value};
use std::time::Duration;

use crate::signin_logic::{origin_of, Hosts};

const BEGIN: &str = "/api/auth/google/native/begin";
const TOKEN: &str = "/api/auth/google/native/token";
const UNLOCK: &str = "/api/auth/google/native/unlock";
const EVENT: &str = "/api/auth/google/native/event";
const CLASSIFY: &str = "/api/auth/google/native/classify";
const CLIENT_HEADER: &str = "X-FindPlus-Client";
const CLIENT_VALUE: &str = "signin-window";
/// The dashboard's session cookie name (cli/src/findplus/api/__init__.py).
pub const SESSION_COOKIE: &str = "findplus_session";
const MSG_UNREACHABLE: &str = "Find+ could not reach its background service. Try again.";
const MSG_LOCKED: &str = "Find+ is locked. Unlock it, then try again.";

/// A refused or failed call. `status` 0 means the daemon did not answer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApiError {
    pub status: u16,
    pub code: String,
    pub message: String,
}

/// What `begin` returns (from Rust's own call, or handed over by the card).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Begin {
    pub state: String,
    pub unlock_url: Option<String>,
}

/// What `token` returns.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TokenReply {
    pub account: Option<String>,
    pub needs_unlock: bool,
}

/// One daemon, as seen by one sign-in window.
#[derive(Debug, Clone)]
pub struct Daemon {
    pub base: String,
    /// `findplus_session=<value>` when the dashboard has one, else None.
    pub cookie: Option<String>,
}

impl Daemon {
    fn post(&self, path: &str, body: &Value) -> Result<Value, ApiError> {
        let down = || ApiError {
            status: 0,
            code: "unreachable".into(),
            message: MSG_UNREACHABLE.into(),
        };
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(75))
            .build()
            .map_err(|_| down())?;
        let mut req = client
            .post(format!("{}{path}", self.base))
            .header("Origin", self.base.as_str())
            .header(CLIENT_HEADER, CLIENT_VALUE)
            .json(body);
        if let Some(c) = &self.cookie {
            req = req.header("Cookie", c.as_str());
        }
        let resp = req.send().map_err(|_| down())?;
        let status = resp.status().as_u16();
        let parsed: Value = resp.json().unwrap_or(Value::Null);
        if (200..300).contains(&status) {
            Ok(parsed)
        } else {
            Err(api_error(status, &parsed))
        }
    }

    /// Mint the single-use state. `mode` is "signin" or "unlock".
    pub fn begin(&self, mode: &str, hosts: &Hosts) -> Result<Begin, ApiError> {
        let v = self.post(BEGIN, &json!({ "mode": mode }))?;
        parse_begin(&v, hosts).ok_or_else(|| api_error(502, &Value::Null))
    }

    /// Hand the token to the daemon. The token is consumed here.
    pub fn token(&self, state: &str, oauth_token: String) -> Result<TokenReply, ApiError> {
        let v = self.post(
            TOKEN,
            &json!({ "state": state, "oauth_token": oauth_token }),
        )?;
        Ok(parse_token(&v))
    }

    /// Hand the vault keys to the daemon. The keys are consumed here.
    pub fn unlock(
        &self,
        state: &str,
        vault_keys: String,
        hint: Option<&str>,
    ) -> Result<(), ApiError> {
        let body = json!({ "state": state, "vault_keys": vault_keys, "account_hint": hint });
        self.post(UNLOCK, &body).map(|_| ())
    }

    /// Best effort: tell the daemon what the window is doing, for the card.
    pub fn event(&self, state: &str, event: &str, reason: Option<&str>) {
        let body = json!({ "state": state, "event": event, "reason": reason });
        if let Err(e) = self.post(EVENT, &body) {
            log::debug!("signin: event {event} not recorded ({})", e.code);
        }
    }

    /// Ask the daemon whether a loaded page is Google refusing the window.
    /// Returns the blocked reason, or None (not blocked, or no answer).
    pub fn classify(
        &self,
        state: &str,
        host: &str,
        path: &str,
        title_class: &str,
    ) -> Option<String> {
        let body =
            json!({ "state": state, "host": host, "path": path, "title_class": title_class });
        let v = self.post(CLASSIFY, &body).ok()?;
        if v.get("blocked").and_then(Value::as_bool) != Some(true) {
            return None;
        }
        Some(
            v.get("reason")
                .and_then(Value::as_str)
                .unwrap_or("other")
                .to_string(),
        )
    }
}

/// Pure: an unlock URL Find+ will navigate to: Google's own unlock page (or
/// the debug fake server). Anything else is dropped.
pub fn valid_unlock_url(url: &str, hosts: &Hosts) -> bool {
    let origin = origin_of(url);
    let path_ok = url[origin.len().min(url.len())..].starts_with("/encryption/unlock/");
    path_ok
        && (origin == "https://accounts.google.com"
            || hosts.test_origin.as_deref() == Some(&*origin))
}

/// Pure: `{state, unlock_url}` from a begin reply (Rust's or the card's).
pub fn parse_begin(v: &Value, hosts: &Hosts) -> Option<Begin> {
    let state = v
        .get("state")?
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)?;
    let unlock_url = v
        .get("unlock_url")
        .and_then(Value::as_str)
        .filter(|u| valid_unlock_url(u, hosts))
        .map(String::from);
    Some(Begin {
        state: state.to_string(),
        unlock_url,
    })
}

/// Pure: `{account, needs_unlock}` from the token reply.
pub fn parse_token(v: &Value) -> TokenReply {
    TokenReply {
        account: v.get("account").and_then(Value::as_str).map(String::from),
        needs_unlock: v
            .get("needs_unlock")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    }
}

/// Pure: an error for a refused call. The daemon's `detail` is already
/// user-facing; anything that looks like a credential is dropped.
pub fn api_error(status: u16, body: &Value) -> ApiError {
    let code = body
        .get("code")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let detail = body.get("detail").and_then(Value::as_str).unwrap_or("");
    let looks_secret =
        detail.contains("oauth2_4/") || detail.contains("vault") || detail.len() > 300;
    let message = if status == 401 {
        MSG_LOCKED.to_string()
    } else if detail.is_empty() || looks_secret {
        format!("Find+ could not finish signing in (error {status}).")
    } else {
        detail.to_string()
    };
    ApiError {
        status,
        code,
        message,
    }
}

#[cfg(test)]
#[path = "signin_http_tests.rs"]
mod tests;

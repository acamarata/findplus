//! In-app sign-in: the loopback calls to the daemon's native sign-in routes.
//!
//! Purpose    : begin (mint the single-use state), token (hand over the
//!              oauth_token), unlock (hand over the vault keys) and event (tell
//!              the dashboard card what the window is doing). Spec §2.2.
//! Inputs     : The daemon base URL and, when the dashboard is unlocked behind
//!              a PIN, its session cookie read from the main window.
//! Outputs    : Parsed replies, or a message that is safe to show.
//! Constraints: Blocking reqwest; call only from a worker thread. The token
//!              and the vault keys are moved into one request body each and
//!              never formatted, logged or put in an error. `error_message` is
//!              pure and unit-tested.

use serde_json::{json, Value};
use std::time::Duration;

const BEGIN: &str = "/api/auth/google/native/begin";
const TOKEN: &str = "/api/auth/google/native/token";
const UNLOCK: &str = "/api/auth/google/native/unlock";
const EVENT: &str = "/api/auth/google/native/event";
/// The daemon accepts the ingest posts only with this header and the
/// daemon's own 127.0.0.1 Origin (`_routes_auth_google_native._require_shell`).
const CLIENT_HEADER: &str = "X-FindPlus-Client";
const CLIENT_VALUE: &str = "signin-window";
/// The dashboard's session cookie name (cli/src/findplus/api/__init__.py).
pub const SESSION_COOKIE: &str = "findplus_session";
const MSG_UNREACHABLE: &str = "Find+ could not reach its background service. Try again.";
const MSG_LOCKED: &str = "Find+ is locked. Unlock it, then try again.";

/// What `begin` returns.
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
    fn post(&self, path: &str, body: &Value) -> Result<Value, String> {
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(60))
            .build()
            .map_err(|_| MSG_UNREACHABLE.to_string())?;
        let mut req = client
            .post(format!("{}{path}", self.base))
            .header("Origin", self.base.as_str())
            .header(CLIENT_HEADER, CLIENT_VALUE)
            .json(body);
        if let Some(c) = &self.cookie {
            req = req.header("Cookie", c.as_str());
        }
        let resp = req.send().map_err(|_| MSG_UNREACHABLE.to_string())?;
        let status = resp.status().as_u16();
        let parsed: Value = resp.json().unwrap_or(Value::Null);
        if (200..300).contains(&status) {
            Ok(parsed)
        } else {
            Err(error_message(status, &parsed))
        }
    }

    /// Mint the single-use state. `mode` is "signin" or "unlock".
    pub fn begin(&self, mode: &str) -> Result<Begin, String> {
        let v = self.post(BEGIN, &json!({ "mode": mode }))?;
        parse_begin(&v).ok_or_else(|| MSG_UNREACHABLE.to_string())
    }

    /// Hand the token to the daemon. The token is consumed here.
    pub fn token(&self, state: &str, oauth_token: String) -> Result<TokenReply, String> {
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
        account: Option<&str>,
    ) -> Result<(), String> {
        let mut body = json!({ "state": state, "vault_keys": vault_keys });
        if let Some(a) = account {
            body["account_hint"] = json!(a);
        }
        self.post(UNLOCK, &body).map(|_| ())
    }

    /// Best effort: tell the daemon what the window is doing, for the card.
    pub fn event(&self, state: &str, event: &str, reason: Option<&str>) {
        let mut body = json!({ "state": state, "event": event });
        if let Some(r) = reason {
            body["reason"] = json!(r);
        }
        if let Err(e) = self.post(EVENT, &body) {
            log::debug!("signin: event {event} not recorded: {e}");
        }
    }
}

/// Pure: `{state, unlock_url}` from the begin reply.
pub fn parse_begin(v: &Value) -> Option<Begin> {
    let state = v
        .get("state")?
        .as_str()
        .filter(|s| !s.is_empty())?
        .to_string();
    let unlock_url = v
        .get("unlock_url")
        .and_then(Value::as_str)
        .filter(|u| u.starts_with("https://") || cfg!(debug_assertions))
        .map(String::from);
    Some(Begin { state, unlock_url })
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

/// Pure: a message safe to show for a failed call. The daemon's `detail` is
/// already user-facing; anything that looks like a credential is dropped.
pub fn error_message(status: u16, body: &Value) -> String {
    if status == 401 {
        return MSG_LOCKED.to_string();
    }
    let detail = body.get("detail").and_then(Value::as_str).unwrap_or("");
    let looks_secret =
        detail.contains("oauth2_4/") || detail.contains("vault") || detail.len() > 300;
    if detail.is_empty() || looks_secret {
        return format!("Find+ could not finish signing in (error {status}).");
    }
    detail.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn begin_reply_parses_and_rejects_empty_state() {
        let v = json!({"state": "s1", "unlock_url": "https://accounts.google.com/encryption/unlock/android?kdi=x"});
        let b = parse_begin(&v).unwrap();
        assert_eq!(b.state, "s1");
        assert!(b
            .unlock_url
            .unwrap()
            .starts_with("https://accounts.google.com/"));
        assert!(parse_begin(&json!({"state": ""})).is_none());
        assert!(parse_begin(&json!({})).is_none());
        assert_eq!(
            parse_begin(&json!({"state": "s"})).unwrap().unlock_url,
            None
        );
    }

    #[test]
    fn token_reply_defaults_to_no_unlock() {
        let r = parse_token(&json!({"account": "a@b.com", "needs_unlock": true}));
        assert_eq!(
            r,
            TokenReply {
                account: Some("a@b.com".into()),
                needs_unlock: true
            }
        );
        assert_eq!(
            parse_token(&json!({})),
            TokenReply {
                account: None,
                needs_unlock: false
            }
        );
    }

    #[test]
    fn error_messages_never_carry_a_credential() {
        assert_eq!(error_message(401, &Value::Null), MSG_LOCKED);
        let leak = json!({"detail": "bad token oauth2_4/abc"});
        assert!(!error_message(400, &leak).contains("oauth2_4"));
        let ok = json!({"detail": "Google refused the sign-in. Try again."});
        assert_eq!(
            error_message(400, &ok),
            "Google refused the sign-in. Try again."
        );
        assert!(error_message(500, &Value::Null).contains("500"));
    }
}

//! In-app sign-in: pure facts about pages and cookies (no Tauri, no network).
//!
//! Purpose    : Is this page Google refusing an embedded browser? Which cookie
//!              is the sign-in cookie? What may a log or the daemon see of a URL?
//! Outputs    : Plain values; nothing here logs, stores or sends anything.
//! Constraints: `pick_oauth_token` is the only function that returns a cookie
//!              value. Re-exported through signin_logic.rs.

use crate::signin_logic::{origin_of, Hosts, BRIDGE_HOST};

/// Pure: the reason a page looks like Google refusing an embedded browser,
/// from the URL (query read only to detect, never stored) and the title. The
/// words are the daemon's `blocked` reasons (native_messages.BLOCKED_REASONS).
pub fn blocked_signal(url: &str, title: &str) -> Option<&'static str> {
    let lower = url.to_lowercase();
    let path = lower.split(['?', '#']).next().unwrap_or("");
    if lower.contains("disallowed_useragent") {
        return Some("disallowed_useragent");
    }
    if path.contains("/signin/rejected") {
        return Some("rejected_page");
    }
    let t = title.to_lowercase().replace('\u{2019}', "'");
    if t.contains("may not be secure") {
        return Some("rejected_page");
    }
    None
}

/// Pure: is this the "signed in, account home" page the unlock-only mode waits for?
pub fn is_account_home(url: &str, hosts: &Hosts) -> bool {
    if origin_of(url) == "https://myaccount.google.com" {
        return true;
    }
    let test = hosts
        .test_origin
        .as_deref()
        .filter(|t| origin_of(url) == *t);
    test.is_some_and(|t| url[t.len()..].starts_with("/myaccount"))
}

/// One cookie, as much as the picker needs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CookieFacts {
    pub name: String,
    pub value: String,
    pub domain: String,
    /// Unix seconds; None for a session cookie.
    pub expires: Option<i64>,
}

/// Pure: the `oauth_token` value, if a live Google one is present. wry's macOS
/// `cookies_for_url` keeps only exact-host matches, so the caller reads every
/// cookie and this does the matching.
pub fn pick_oauth_token(cookies: &[CookieFacts], now: i64, hosts: &Hosts) -> Option<String> {
    let test_host = hosts
        .test_origin
        .as_deref()
        .map(|o| host_of_origin(o).to_string());
    cookies
        .iter()
        .find(|c| {
            let d = c.domain.trim_start_matches('.');
            let google = d == "google.com" || d.ends_with(".google.com");
            let test = test_host.as_deref() == Some(d);
            c.name == "oauth_token"
                && c.value.starts_with("oauth2_4/")
                && (google || test)
                && c.expires.is_none_or(|e| e > now)
        })
        .map(|c| c.value.clone())
}

fn host_of_origin(origin: &str) -> &str {
    let rest = origin.split_once("://").map_or(origin, |(_, r)| r);
    rest.split(':').next().unwrap_or(rest)
}

/// Pure: `scheme://host/path` for logs. No query, no fragment, no user info,
/// and the bridge URL collapses to its kind so keys can never reach a log.
pub fn redact_url(url: &str) -> String {
    let (scheme, rest) = url.split_once("://").unwrap_or(("", url));
    let rest = rest.split(['?', '#']).next().unwrap_or("");
    let rest = rest.rsplit_once('@').map_or(rest, |(_, r)| r);
    let (host, path) = rest.split_once('/').map_or((rest, ""), |(h, p)| (h, p));
    if host == BRIDGE_HOST {
        return format!("{scheme}://{host}/<bridge>");
    }
    format!("{scheme}://{host}/{path}")
}

/// Pure: host and path (no query, no fragment) for the daemon's classify route.
pub fn host_and_path(url: &str) -> (String, String) {
    let rest = url.split_once("://").map_or(url, |(_, r)| r);
    let rest = rest.split(['?', '#']).next().unwrap_or("");
    let (auth, path) = rest.split_once('/').map_or((rest, ""), |(h, p)| (h, p));
    let host = auth.rsplit_once('@').map_or(auth, |(_, h)| h);
    let host = host.split(':').next().unwrap_or("").to_lowercase();
    (
        host,
        format!("/{}", path.chars().take(511).collect::<String>()),
    )
}

/// Pure: the coarse title class the daemon accepts (contract §3.5).
pub fn title_class(title: &str) -> &'static str {
    let t = title.to_lowercase().replace('\u{2019}', "'");
    if t.is_empty() {
        "unknown"
    } else if t.contains("may not be secure") {
        "browser_not_secure"
    } else if t.contains("couldn't sign you in") {
        "couldnt_sign_in"
    } else {
        "normal"
    }
}

/// Pure: a non-reversible fingerprint, so a refused cookie value is not
/// posted again without keeping the value itself.
pub fn fingerprint(s: &str) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    s.hash(&mut h);
    h.finish()
}

/// Pure: the window title, naming the host the person is typing into.
pub fn window_title(provider_name: &str, host: &str) -> String {
    format!("Find+ sign-in: {provider_name} ({host})")
}

#[cfg(test)]
#[path = "signin_page_tests.rs"]
mod tests;

//! Package 0 gate probe: pure decision logic (no Tauri, no network).
//!
//! Purpose    : Decide what a Google embedded sign-in attempt looked like and
//!              turn it into a plain-words report. Debug/dev tool only.
//! Constraints: Never holds, logs or prints a cookie value. Cookies enter as
//!              `CookieInfo` (name, domain, value LENGTH). URLs are reduced to
//!              host + path before they are stored.
#![cfg_attr(not(feature = "login-probe"), allow(dead_code))]

/// Hosts the probe window may navigate to (https only).
pub const ALLOWED_HOSTS: &[&str] = &[
    "accounts.google.com",
    "accounts.youtube.com",
    "myaccount.google.com",
    "consent.google.com",
    "www.google.com",
    "google.com",
    "ssl.gstatic.com",
    "www.gstatic.com",
];

/// What the probe decided about the final page.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    SignedIn,
    Rejected,
    Unknown,
}

/// A cookie reduced to what the report may say. No value, ever.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CookieInfo {
    pub name: String,
    pub domain: String,
    pub value_len: usize,
}

/// Everything the report needs.
#[derive(Debug, Clone)]
pub struct ProbeFacts {
    pub trail: Vec<String>,
    pub final_url: String,
    pub final_title: String,
    pub page_text_rejected: Option<bool>,
    pub blocked_hosts: Vec<String>,
    pub cookie_len: Option<usize>,
    pub user_agent: String,
    pub seconds: u64,
    pub fake_server: bool,
}

/// Pure: may the window go to `url`? `allow_loopback` is the fake-server mode.
pub fn allow_navigation(scheme: &str, host: &str, allow_loopback: bool) -> bool {
    if allow_loopback && scheme == "http" && host == "127.0.0.1" {
        return true;
    }
    scheme == "https" && ALLOWED_HOSTS.contains(&host)
}

/// Pure: `host/path` only. No query, no fragment, long id-like segments hidden.
pub fn redact(url: &str) -> String {
    let rest = url.split_once("://").map_or(url, |(_, r)| r);
    let rest = rest.split(['?', '#']).next().unwrap_or("");
    let (host, path) = rest.split_once('/').map_or((rest, ""), |(h, p)| (h, p));
    let path: Vec<String> = path.split('/').map(hide_long_segment).collect();
    format!("{host}/{}", path.join("/"))
}

fn hide_long_segment(seg: &str) -> String {
    if seg.len() > 24 {
        "<long>".to_string()
    } else {
        seg.to_string()
    }
}

/// Pure: which rejection signal matched, if any. Looks at the full URL (query
/// included, only to detect, never to store) and the page title.
pub fn rejection_signal(url: &str, title: &str) -> Option<String> {
    let lower = url.to_lowercase();
    let path = lower.split(['?', '#']).next().unwrap_or("");
    if lower.contains("disallowed_useragent") {
        return Some("URL contains disallowed_useragent".to_string());
    }
    if path.contains("/signin/rejected") {
        return Some("URL path is /signin/rejected".to_string());
    }
    let t = title.to_lowercase();
    for phrase in ["may not be secure", "couldn't sign you in", "couldn\u{2019}t sign you in"] {
        if t.contains(phrase) {
            return Some(format!("page title says \"{title}\""));
        }
    }
    None
}

/// Pure: classify the end state. A rejection signal wins over a cookie.
pub fn classify(url: &str, title: &str, cookie_found: bool, page_rejected: bool) -> Verdict {
    if page_rejected || rejection_signal(url, title).is_some() {
        Verdict::Rejected
    } else if cookie_found {
        Verdict::SignedIn
    } else {
        Verdict::Unknown
    }
}

/// Pure: length of the first `oauth_token` cookie, if any. Value never read.
pub fn find_oauth_token(cookies: &[CookieInfo]) -> Option<usize> {
    cookies.iter().find(|c| c.name == "oauth_token").map(|c| c.value_len)
}

/// Pure: append to the trail without consecutive duplicates, capped at 40.
pub fn push_trail(trail: &mut Vec<String>, entry: String) {
    if trail.last() != Some(&entry) && trail.len() < 40 {
        trail.push(entry);
    }
}

/// Pure: the plain-words report. Contains no secrets by construction.
pub fn report_text(f: &ProbeFacts) -> String {
    let verdict = classify(
        &f.final_url,
        &f.final_title,
        f.cookie_len.is_some(),
        f.page_text_rejected == Some(true),
    );
    let mut out = String::from("Find+ Google embedded sign-in probe\n");
    out += &format!("Result: {}\n", verdict_line(verdict));
    out += &format!("Ended on: {}\n", redact(&f.final_url));
    out += &format!("Rejection: {}\n", rejection_line(f));
    out += &match f.cookie_len {
        Some(n) => format!("oauth_token cookie: YES (length {n}, value not recorded)\n"),
        None => "oauth_token cookie: NO\n".to_string(),
    };
    out += &format!("User agent: {}\n", f.user_agent);
    out += &format!("Time: {} seconds\n", f.seconds);
    if f.fake_server {
        out += "Note: this ran against the local fake server, not Google.\n";
    }
    if !f.blocked_hosts.is_empty() {
        out += &format!("Blocked by allow-list: {}\n", f.blocked_hosts.join(", "));
    }
    out += &format!("Pages seen: {}\n", f.trail.join(" > "));
    out
}

fn verdict_line(v: Verdict) -> &'static str {
    match v {
        Verdict::SignedIn => "SIGNED IN (cookie found, no rejection page)",
        Verdict::Rejected => "REJECTED (Google refused the embedded window)",
        Verdict::Unknown => "UNKNOWN (no cookie, no rejection page seen)",
    }
}

fn rejection_line(f: &ProbeFacts) -> String {
    if let Some(s) = rejection_signal(&f.final_url, &f.final_title) {
        return format!("YES, {s}");
    }
    match f.page_text_rejected {
        Some(true) => "YES, page text mentions a secure-browser or disallowed-agent message".into(),
        Some(false) => "none seen (checked URL, title and page text)".into(),
        None => "none seen in URL or title (page text could not be checked)".into(),
    }
}

#[cfg(test)]
#[path = "probe_logic_tests.rs"]
mod tests;

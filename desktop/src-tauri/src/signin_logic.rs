//! In-app sign-in: pure decision logic (no Tauri, no network, no clock).
//!
//! Purpose    : Everything the sign-in window decides that can be unit-tested:
//!              which URLs it may load, whether a page is Google refusing an
//!              embedded browser, which cookie is the sign-in cookie, how a URL
//!              is shortened for logs, and how a bridge message is decoded.
//!              The state machine lives in `signin_machine.rs`; page facts
//!              (blocked pages, the cookie picker, redaction) in signin_page.rs.
//! Inputs     : URL parts, page titles, cookie facts, bridge URLs.
//! Outputs    : Plain values; nothing here logs, stores or sends anything.
//! Constraints: 127.0.0.1 and localhost are never allowed unless a debug-only
//!              test origin is passed in (`Hosts::test_origin`, always None in
//!              a release build). The cookie value is returned only by
//!              `pick_oauth_token` and never formatted anywhere in this file.
//!              Spec: .github/docs/specs/in-app-login.md §2, §3.4, §4, §9.

/// The page the Google sign-in window starts on.
pub const GOOGLE_SIGNIN_START: &str = "https://accounts.google.com/EmbeddedSetup";
/// The page the unlock-only mode starts on (the vendored flow does the same).
pub const GOOGLE_UNLOCK_START: &str = "https://accounts.google.com/";
/// The fake host the unlock bridge navigates to. `.invalid` never resolves
/// (RFC 2606) and the navigation is cancelled before any request is made.
pub const BRIDGE_HOST: &str = "findplus-bridge.invalid";
/// Largest bridge fragment accepted, before decoding.
pub const BRIDGE_MAX_BYTES: usize = 64 * 1024;

// Page facts (blocked pages, cookies, redaction) live in signin_page.rs.
pub use crate::signin_page::*;

/// Exact hosts the window may load over https. Google's sign-in pages embed
/// frames from several of these, and on macOS every frame's navigation goes
/// through the same handler, so the list covers frames as well as pages.
const ALLOWED_HOSTS: &[&str] = &[
    "accounts.google.com",
    "accounts.youtube.com",
    "myaccount.google.com",
    "www.google.com",
    "ssl.gstatic.com",
    "www.gstatic.com",
    "consent.google.com",
    "ogs.google.com",
];

/// Where the window is allowed to go, plus the debug-only test origin.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Hosts {
    /// `http://127.0.0.1:<port>` in a debug self-test, else None.
    pub test_origin: Option<String>,
}

/// What the navigation handler should do with one URL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Nav {
    Allow,
    /// A bridge message: cancel the navigation and act on it.
    Bridge(Bridge),
    /// Refused. Carries the host only, for the log.
    Block(String),
    /// Refused, and the page is leaving Google (a Workspace account's own
    /// sign-in page, for example). The window cannot finish here.
    Outside(String),
}

/// A message from the init script, carried in a cancelled navigation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Bridge {
    /// The unlock page's vault keys, as the JSON string it produced.
    Vault(String),
    /// The unlock page asked to close without keys.
    Close,
    /// The person pressed Cmd+W (or Ctrl+W) inside the page.
    Cancel,
    /// The signed-in Google address, read from myaccount.google.com.
    Account(String),
    /// The account page loaded but no address could be read from it.
    NoAccount,
    /// A bridge URL that could not be decoded. Never acted on.
    Bad,
}

/// Pure: `accounts.google.<cc>` for a country domain (`.de`, `.co.uk`, `.com.br`).
fn is_google_country_accounts(host: &str) -> bool {
    let Some(tail) = host.strip_prefix("accounts.google.") else {
        return false;
    };
    let two = |s: &str| s.len() == 2 && s.bytes().all(|b| b.is_ascii_lowercase());
    match tail.split_once('.') {
        None => two(tail),
        Some((first, rest)) => (first == "co" || first == "com") && two(rest),
    }
}

/// Pure: is this https host on the allow-list?
pub fn is_allowed_host(host: &str) -> bool {
    ALLOWED_HOSTS.contains(&host) || is_google_country_accounts(host)
}

/// Pure: the origin (`scheme://host[:port]`) of a URL string, lowercased.
pub fn origin_of(url: &str) -> String {
    let (scheme, rest) = url.split_once("://").unwrap_or(("", url));
    let auth = rest.split(['/', '?', '#']).next().unwrap_or("");
    format!("{}://{}", scheme.to_lowercase(), auth.to_lowercase())
}

/// Pure: decide one navigation. `scheme`/`host` come from the parsed URL;
/// `url` is the full string (needed for the bridge fragment).
pub fn decide_navigation(url: &str, scheme: &str, host: &str, hosts: &Hosts) -> Nav {
    if scheme == "https" && host == BRIDGE_HOST {
        return Nav::Bridge(decode_bridge(url));
    }
    // Blank frames load nothing from the network; Google's pages create them.
    if scheme == "about" && (url == "about:blank" || url == "about:srcdoc") {
        return Nav::Allow;
    }
    if let Some(test) = &hosts.test_origin {
        if origin_of(url) == *test {
            return Nav::Allow;
        }
    }
    if scheme == "https" && is_allowed_host(host) {
        return Nav::Allow;
    }
    if (scheme == "https" || scheme == "http") && !host.is_empty() && !is_google_family(host) {
        return Nav::Outside(host.to_string());
    }
    Nav::Block(host.to_string())
}

/// Pure: a Google-owned host. A refused frame on one of these is ignored; a
/// refused navigation anywhere else means the sign-in left Google.
pub fn is_google_family(host: &str) -> bool {
    const SUFFIXES: &[&str] = &[
        "google.com",
        "gstatic.com",
        "googleapis.com",
        "googleusercontent.com",
        "youtube.com",
        "googlevideo.com",
        "doubleclick.net",
    ];
    let family = |s: &&str| host == *s || host.ends_with(&format!(".{s}"));
    SUFFIXES.iter().any(family)
        || host.starts_with("accounts.google.") && is_google_country_accounts(host)
}

/// Pure: decode `https://findplus-bridge.invalid/<kind>#<base64url>`.
pub fn decode_bridge(url: &str) -> Bridge {
    let Some(rest) = url.strip_prefix("https://findplus-bridge.invalid/") else {
        return Bridge::Bad;
    };
    let (kind, frag) = rest.split_once('#').unwrap_or((rest, ""));
    if frag.len() > BRIDGE_MAX_BYTES {
        return Bridge::Bad;
    }
    match kind {
        "close" => Bridge::Close,
        "cancel" => Bridge::Cancel,
        "noaccount" => Bridge::NoAccount,
        "vault" | "account" => match b64url_decode(frag).and_then(|b| String::from_utf8(b).ok()) {
            Some(s) if s.is_empty() => Bridge::Bad,
            Some(s) if kind == "vault" => Bridge::Vault(s),
            Some(s) if s.contains('@') && s.len() <= 320 => Bridge::Account(s),
            _ => Bridge::Bad,
        },
        _ => Bridge::Bad,
    }
}

/// Pure: base64url (no padding, padding tolerated) to bytes. None when invalid.
pub fn b64url_decode(s: &str) -> Option<Vec<u8>> {
    fn val(c: u8) -> Option<u32> {
        match c {
            b'A'..=b'Z' => Some((c - b'A') as u32),
            b'a'..=b'z' => Some((c - b'a' + 26) as u32),
            b'0'..=b'9' => Some((c - b'0' + 52) as u32),
            b'-' => Some(62),
            b'_' => Some(63),
            _ => None,
        }
    }
    let s = s.trim_end_matches('=').as_bytes();
    if s.len() % 4 == 1 {
        return None;
    }
    let mut out = Vec::with_capacity(s.len() * 3 / 4);
    for chunk in s.chunks(4) {
        let mut acc = 0u32;
        for (i, &c) in chunk.iter().enumerate() {
            acc |= val(c)? << (18 - 6 * i);
        }
        let bytes = acc.to_be_bytes();
        out.extend_from_slice(&bytes[1..chunk.len()]);
    }
    Some(out)
}

#[cfg(test)]
#[path = "signin_logic_tests.rs"]
mod tests;

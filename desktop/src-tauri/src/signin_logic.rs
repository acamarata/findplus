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

// Which hosts the window may load (Google's sign-in infrastructure) and when a
// refusal means the sign-in left Google live in signin_hosts.rs.
pub use crate::signin_hosts::{authority_is_plain, host_shape_ok, is_allowed_host};

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
    /// Refused, and the host is not Google's. Either a frame (ignored) or
    /// the main frame leaving Google (a Workspace account's own sign-in
    /// page); the session tells them apart with `FrameWatch`.
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
    if scheme == "https" && authority_is_plain(url) && is_allowed_host(host) {
        return Nav::Allow;
    }
    // Off Google entirely (another company's sign-in page, or a third-party
    // frame): the session decides whether it was the main frame (FrameWatch).
    if (scheme == "https" || scheme == "http") && host_shape_ok(host) && !is_allowed_host(host) {
        return Nav::Outside(host.to_string());
    }
    // A Google host over http, with a port or a user@ part, an IP literal,
    // or an odd scheme: refused quietly.
    Nav::Block(host.to_string())
}

/// This process's bridge key: 128 random bits from the OS (the std hasher
/// keys), made once. Only the main frame's init script holds it, so a frame
/// from another origin (the allow-list includes Google's user-content hosts)
/// cannot forge a bridge message: no key, no message.
pub fn bridge_key() -> &'static str {
    static KEY: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    KEY.get_or_init(|| {
        use std::hash::{BuildHasher, Hasher};
        let part = || {
            let mut h = std::collections::hash_map::RandomState::new().build_hasher();
            h.write_u128(std::time::UNIX_EPOCH.elapsed().map_or(0, |d| d.as_nanos()));
            h.finish()
        };
        format!("{:016x}{:016x}", part(), part())
    })
}

/// Pure: decode `https://findplus-bridge.invalid/<key>/<kind>#<base64url>`.
/// A message without this process's key is `Bad` (never acted on).
pub fn decode_bridge(url: &str) -> Bridge {
    let Some(rest) = url
        .strip_prefix("https://findplus-bridge.invalid/")
        .and_then(|r| r.strip_prefix(bridge_key()))
        .and_then(|r| r.strip_prefix('/'))
    else {
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

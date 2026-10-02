//! In-app sign-in: which hosts the window may load, and when a refused
//! navigation means the sign-in left Google (pure; no Tauri, no clock).
//!
//! Purpose    : wry calls the navigation handler for the main frame AND for
//!              every sub-frame, with the URL only (no frame flag). So the
//!              allow-list covers Google's own sign-in infrastructure (frames
//!              included), and a refused off-Google host only counts as
//!              "left Google" when it can be a top-level navigation
//!              (`FrameWatch`). A sub-frame refusal is logged and ignored.
//! Inputs     : Host names as the url crate gives them (lowercase, punycode).
//! Outputs    : `is_allowed_host`, `authority_is_plain`, `FrameWatch`.
//! Constraints: Look-alikes (`google.com.evil.net`, `evilgoogle.com`), IP
//!              literals, empty labels and trailing dots are never allowed.
//!              Keep in step with native_classify.is_allowed_host (daemon).
//!              Spec: .github/docs/specs/in-app-login.md §9.1.

/// Exact hosts outside the families below.
const EXACT: &[&str] = &["accounts.youtube.com"];

/// Google-owned registrable domains: the domain or any subdomain of it.
/// (google.com, the static and API hosts Google's sign-in pages load, user
/// photo hosts, and reCAPTCHA's own domain.)
const FAMILIES: &[&str] = &[
    "google.com",
    "gstatic.com",
    "googleapis.com",
    "googleusercontent.com",
    "recaptcha.net",
];

/// How long a refused off-Google navigation waits for a new main-frame page
/// before it counts as the sign-in leaving Google.
pub const OUTSIDE_GRACE_MS: u64 = 1500;

/// Pure: one DNS label (lowercase letters, digits, inner hyphens).
fn label_ok(l: &str) -> bool {
    let b = l.as_bytes();
    !b.is_empty()
        && b.len() <= 63
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
        && b[0] != b'-'
        && b[b.len() - 1] != b'-'
}

/// Pure: a plain DNS name: no empty label, no trailing dot, not an IP.
pub fn host_shape_ok(host: &str) -> bool {
    let labels: Vec<&str> = host.split('.').collect();
    host.len() <= 253
        && labels.len() >= 2
        && labels.iter().all(|l| label_ok(l))
        && !labels[labels.len() - 1].bytes().all(|c| c.is_ascii_digit())
}

/// Pure: `host` is `domain` or a subdomain of it (never `evil-domain`).
fn under(host: &str, domain: &str) -> bool {
    host == domain || host.strip_suffix(domain).is_some_and(|p| p.ends_with('.'))
}

/// Pure: `[sub.]google.<cc>`, `google.co.<cc>` or `google.com.<cc>`.
fn google_country(host: &str) -> bool {
    let l: Vec<&str> = host.split('.').collect();
    let two = |s: &str| s.len() == 2 && s.bytes().all(|b| b.is_ascii_lowercase());
    let n = l.len();
    if n >= 2 && two(l[n - 1]) && l[n - 2] == "google" {
        return true;
    }
    n >= 3 && two(l[n - 1]) && matches!(l[n - 2], "co" | "com") && l[n - 3] == "google"
}

/// Pure: may the sign-in window load this https host (page or frame)?
pub fn is_allowed_host(host: &str) -> bool {
    host_shape_ok(host)
        && (EXACT.contains(&host)
            || FAMILIES.iter().any(|d| under(host, d))
            || google_country(host))
}

/// Pure: the URL's authority is a bare host: no `user@` part and no port.
/// (The url crate drops a default port, so any port left is not 443.)
pub fn authority_is_plain(url: &str) -> bool {
    let rest = url.split_once("://").map_or("", |(_, r)| r);
    let auth = rest.split(['/', '?', '#']).next().unwrap_or("");
    !auth.is_empty() && !auth.contains('@') && !auth.contains(':')
}

/// Tells a top-level departure from Google apart from a sub-frame load.
///
/// wry reports `PageLoadEvent::Started` when the MAIN frame commits a page
/// and `Finished` when it is done; sub-frames load in between. A refused
/// off-Google URL while a page is still loading is a sub-frame: ignored. One
/// at rest (or before the first page) may be the main frame being sent to
/// another company's sign-in page; it counts once `OUTSIDE_GRACE_MS` pass
/// with no new main-frame page.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct FrameWatch {
    loading: bool,
    pending: Option<(String, u64)>,
}

impl FrameWatch {
    /// The main frame committed a new page: anything pending was not it.
    pub fn committed(&mut self) {
        self.loading = true;
        self.pending = None;
    }

    /// The main frame's page finished loading.
    pub fn finished(&mut self) {
        self.loading = false;
    }

    /// A refused off-Google navigation at `now_ms`. False when it can only
    /// be a sub-frame (ignored); true when it is held as a candidate.
    pub fn refused_outside(&mut self, host: &str, now_ms: u64) -> bool {
        if self.loading {
            return false;
        }
        if self.pending.is_none() {
            self.pending = Some((host.to_string(), now_ms));
        }
        true
    }

    /// The host the sign-in left Google for, once the grace has passed.
    pub fn left_google(&mut self, now_ms: u64) -> Option<String> {
        let due = self
            .pending
            .as_ref()
            .is_some_and(|(_, at)| now_ms.saturating_sub(*at) >= OUTSIDE_GRACE_MS);
        if due {
            self.pending.take().map(|(h, _)| h)
        } else {
            None
        }
    }
}

#[cfg(test)]
#[path = "signin_hosts_tests.rs"]
mod tests;

//! Unit tests for signin_logic.rs (spec §9.3). No network, no webview.
use super::*;

fn none() -> Hosts {
    Hosts::default()
}

fn test_hosts() -> Hosts {
    Hosts {
        test_origin: Some("http://127.0.0.1:5555".into()),
    }
}

fn nav(url: &str, hosts: &Hosts) -> Nav {
    let (scheme, rest) = url.split_once(':').unwrap();
    let host = rest
        .trim_start_matches("//")
        .split(['/', ':', '?', '#'])
        .next()
        .unwrap();
    decide_navigation(url, scheme, host, hosts)
}

#[test]
fn allow_list_table() {
    for ok in [
        "https://accounts.google.com/EmbeddedSetup",
        "https://accounts.google.de/accounts/SetSID",
        "https://accounts.google.co.uk/x",
        "https://accounts.google.com.br/x",
        "https://accounts.youtube.com/accounts/CheckConnection",
        "https://myaccount.google.com/",
        "https://ssl.gstatic.com/x.js",
        "about:blank",
    ] {
        assert_eq!(nav(ok, &none()), Nav::Allow, "{ok}");
    }
    for bad in [
        "http://accounts.google.com/",
        "https://play.google.com/log",
        "https://fonts.googleapis.com/x",
        "file:///etc/passwd",
        "about:config",
        "data:text/html,hi",
    ] {
        assert!(matches!(nav(bad, &none()), Nav::Block(_)), "{bad}");
    }
    for outside in [
        "https://accounts.google.evil.com/",
        "https://accounts.google.co.evil/",
        "https://evil.com/accounts.google.com",
        "https://login.microsoftonline.com/",
        "https://accounts.google.c/",
    ] {
        assert!(
            matches!(nav(outside, &none()), Nav::Outside(_)),
            "{outside}"
        );
    }
}

#[test]
fn loopback_is_never_allowed_without_the_test_origin() {
    for url in [
        "http://127.0.0.1:8647/",
        "http://localhost:8647/",
        "https://127.0.0.1/",
        "http://127.0.0.1:5555/EmbeddedSetup",
    ] {
        assert_ne!(nav(url, &none()), Nav::Allow, "{url}");
    }
}

#[test]
fn the_test_origin_is_an_exact_match() {
    let h = test_hosts();
    assert_eq!(nav("http://127.0.0.1:5555/EmbeddedSetup", &h), Nav::Allow);
    assert_ne!(nav("http://127.0.0.1:8647/", &h), Nav::Allow);
    assert_ne!(nav("http://localhost:5555/", &h), Nav::Allow);
}

fn b64(s: &str) -> String {
    // Test-side encoder, the same alphabet the init script uses.
    const A: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for c in s.as_bytes().chunks(3) {
        let n = c
            .iter()
            .enumerate()
            .fold(0u32, |a, (i, b)| a | (*b as u32) << (16 - 8 * i));
        for i in 0..=c.len() {
            out.push(A[(n >> (18 - 6 * i) & 63) as usize] as char);
        }
    }
    out
}

#[test]
fn bridge_decodes_vault_account_close_cancel() {
    let v = r#"[{"k":"finder_hw"}]"#;
    let url = format!("https://findplus-bridge.invalid/vault#{}", b64(v));
    assert_eq!(nav(&url, &none()), Nav::Bridge(Bridge::Vault(v.into())));
    let url = format!("https://findplus-bridge.invalid/account#{}", b64("a@b.com"));
    assert_eq!(decode_bridge(&url), Bridge::Account("a@b.com".into()));
    assert_eq!(
        decode_bridge("https://findplus-bridge.invalid/close"),
        Bridge::Close
    );
    assert_eq!(
        decode_bridge("https://findplus-bridge.invalid/cancel"),
        Bridge::Cancel
    );
}

#[test]
fn bridge_refuses_bad_input() {
    let bad = [
        "https://findplus-bridge.invalid/vault#%%%".to_string(),
        "https://findplus-bridge.invalid/vault#A".to_string(),
        "https://findplus-bridge.invalid/vault#".to_string(),
        "https://findplus-bridge.invalid/other#abcd".to_string(),
        format!(
            "https://findplus-bridge.invalid/account#{}",
            b64("no-at-sign")
        ),
        format!(
            "https://findplus-bridge.invalid/vault#{}",
            "A".repeat(BRIDGE_MAX_BYTES + 4)
        ),
        "https://evil.invalid/vault#abcd".to_string(),
    ];
    for url in bad {
        assert_eq!(decode_bridge(&url), Bridge::Bad, "{url}");
    }
    // A bad bridge message is still cancelled, never allowed through.
    assert_eq!(
        nav("https://findplus-bridge.invalid/x", &none()),
        Nav::Bridge(Bridge::Bad)
    );
}

#[test]
fn base64url_round_trips_every_length() {
    for s in ["", "a", "ab", "abc", "abcd", "ü€😀 {\"x\":1}"] {
        assert_eq!(b64url_decode(&b64(s)).unwrap(), s.as_bytes(), "{s}");
    }
    assert_eq!(b64url_decode("YQ==").unwrap(), b"a");
    assert!(b64url_decode("a+b/").is_none());
}

#[test]
fn blocked_classifier() {
    let rej = "https://accounts.google.com/v3/signin/rejected?x=1";
    assert_eq!(blocked_signal(rej, ""), Some("rejected_page"));
    let ua = "https://accounts.google.com/o?error=disallowed_useragent";
    assert_eq!(blocked_signal(ua, ""), Some("disallowed_useragent"));
    assert_eq!(
        blocked_signal("https://x/", "Couldn\u{2019}t sign you in"),
        Some("rejected_page")
    );
    assert_eq!(
        blocked_signal("https://x/", "This browser or app may not be secure"),
        Some("rejected_page")
    );
    assert_eq!(
        blocked_signal("https://accounts.google.com/EmbeddedSetup", "Sign in"),
        None
    );
    // Only the path counts for "rejected", not a query value.
    assert_eq!(
        blocked_signal("https://accounts.google.com/a?next=/signin/rejected", ""),
        None
    );
}

fn cookie(name: &str, value: &str, domain: &str, expires: Option<i64>) -> CookieFacts {
    CookieFacts {
        name: name.into(),
        value: value.into(),
        domain: domain.into(),
        expires,
    }
}

#[test]
fn cookie_picker() {
    let good = cookie("oauth_token", "oauth2_4/abc", ".google.com", None);
    let host_only = cookie(
        "oauth_token",
        "oauth2_4/def",
        "accounts.google.com",
        Some(200),
    );
    let n = &none();
    assert_eq!(
        pick_oauth_token(std::slice::from_ref(&good), 100, n).as_deref(),
        Some("oauth2_4/abc")
    );
    assert_eq!(
        pick_oauth_token(&[host_only], 100, n).as_deref(),
        Some("oauth2_4/def")
    );
    let rejects = [
        cookie("oauth_tokens", "oauth2_4/abc", ".google.com", None),
        cookie("oauth_token", "oauth2_3/abc", ".google.com", None),
        cookie("oauth_token", "oauth2_4/abc", ".evilgoogle.com", None),
        cookie("oauth_token", "oauth2_4/abc", ".google.com", Some(99)),
        cookie("oauth_token", "oauth2_4/abc", "127.0.0.1", None),
    ];
    for c in rejects {
        assert_eq!(
            pick_oauth_token(std::slice::from_ref(&c), 100, n),
            None,
            "{c:?}"
        );
    }
    let fake = cookie("oauth_token", "oauth2_4/test", "127.0.0.1", None);
    assert!(pick_oauth_token(&[fake], 100, &test_hosts()).is_some());
}

#[test]
fn redaction_keeps_scheme_host_path_only() {
    let u = "https://user:pw@accounts.google.com/v3/signin/x?continue=secret#frag";
    assert_eq!(redact_url(u), "https://accounts.google.com/v3/signin/x");
    let b = format!("https://findplus-bridge.invalid/vault#{}", b64("keys"));
    assert_eq!(redact_url(&b), "https://findplus-bridge.invalid/<bridge>");
    assert!(!redact_url("https://a.com/p?oauth_token=oauth2_4/x").contains("oauth2_4"));
}

#[test]
fn account_home_and_title() {
    assert!(is_account_home(
        "https://myaccount.google.com/?pli=1",
        &none()
    ));
    assert!(!is_account_home("https://accounts.google.com/", &none()));
    assert!(!is_account_home("http://127.0.0.1:5555/myaccount", &none()));
    assert!(is_account_home(
        "http://127.0.0.1:5555/myaccount",
        &test_hosts()
    ));
    assert_eq!(
        window_title("Google", "accounts.google.com"),
        "Find+ sign-in: Google (accounts.google.com)"
    );
}

/// Spec §9.1: no capability file may name the sign-in window or a Google URL,
/// so Google's page can never reach a Tauri command.
#[test]
fn no_capability_names_the_signin_window_or_google() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("capabilities");
    for entry in std::fs::read_dir(dir).unwrap().flatten() {
        let text = std::fs::read_to_string(entry.path()).unwrap();
        let json: serde_json::Value = serde_json::from_str(&text).unwrap();
        let windows = json["windows"].as_array().cloned().unwrap_or_default();
        for w in &windows {
            let w = w.as_str().unwrap_or("");
            assert!(w == "main" || w == "splash", "{w} in {:?}", entry.path());
        }
        assert!(!text.contains("signin"), "{:?}", entry.path());
        assert!(
            !text.to_lowercase().contains("google"),
            "{:?}",
            entry.path()
        );
        assert!(!text.contains("\"*\""), "{:?}", entry.path());
    }
}

#[test]
fn google_family_hosts() {
    for h in [
        "play.google.com",
        "google.com",
        "fonts.gstatic.com",
        "accounts.google.de",
        "lh3.googleusercontent.com",
    ] {
        assert!(is_google_family(h), "{h}");
    }
    for h in [
        "evilgoogle.com",
        "google.com.evil.net",
        "okta.com",
        "127.0.0.1",
        "accounts.google.evil",
    ] {
        assert!(!is_google_family(h), "{h}");
    }
}

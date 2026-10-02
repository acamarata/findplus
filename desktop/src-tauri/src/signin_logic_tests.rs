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

/// Exactly what the window's handler does: parse with the url crate, decide.
fn nav(url: &str, hosts: &Hosts) -> Nav {
    match tauri::Url::parse(url) {
        Ok(u) => decide_navigation(u.as_str(), u.scheme(), u.host_str().unwrap_or(""), hosts),
        Err(_) => decide_navigation(url, "", "", hosts),
    }
}

#[test]
fn allow_list_table() {
    // Google's sign-in pages and the frames they embed (r12 #2).
    for ok in [
        "https://accounts.google.com/EmbeddedSetup",
        "https://accounts.google.de/accounts/SetSID",
        "https://accounts.google.co.uk/x",
        "https://accounts.google.com.br/x",
        "https://accounts.youtube.com/accounts/CheckConnection",
        "https://myaccount.google.com/",
        "https://ssl.gstatic.com/x.js",
        "https://www.gstatic.com/recaptcha/x.js",
        "https://www.google.com/recaptcha/api2/anchor?k=1",
        "https://www.recaptcha.net/recaptcha/api.js",
        "https://www.google.de/",
        "https://consent.google.de/ml?continue=x",
        "https://consent.google.com/",
        "https://play.google.com/log?format=json",
        "https://apis.google.com/js/api.js",
        "https://fonts.googleapis.com/css",
        "https://lh3.googleusercontent.com/a/photo",
        "https://ACCOUNTS.Google.COM/",
        "about:blank",
        "about:srcdoc",
    ] {
        assert_eq!(nav(ok, &none()), Nav::Allow, "{ok}");
    }
    // Refused quietly: never a reason to stop the sign-in.
    for bad in [
        "http://accounts.google.com/",
        "http://www.google.de/",
        "https://accounts.google.com:8443/",
        "https://user:pw@accounts.google.com/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "file:///etc/passwd",
        "about:config",
        "data:text/html,hi",
        "blob:https://accounts.google.com/x",
        "javascript:alert(1)",
        "ftp://accounts.google.com/",
    ] {
        assert!(matches!(nav(bad, &none()), Nav::Block(_)), "{bad}");
    }
    // Refused, and not Google: a frame, or the main frame leaving Google.
    for outside in [
        "https://accounts.google.evil.com/",
        "https://accounts.google.co.evil/",
        "https://evil.com/accounts.google.com",
        "https://login.microsoftonline.com/",
        "https://accounts.google.c/",
        "https://google.com.evil.net/",
        "https://evilgoogle.com/",
        "https://accounts.google.com@evil.com/",
        "https://accounts.google.com.evil.com:8443/",
        "https://xn--ggle-0nda.com/",
        "https://accounts.gооgle.com/",
        "http://okta.example.com/",
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
        assert!(!text.contains("signin-google"), "{:?}", entry.path());
        assert!(
            !text.to_lowercase().contains("google"),
            "{:?}",
            entry.path()
        );
        assert!(!text.contains("\"*\""), "{:?}", entry.path());
    }
}

//! Unit tests for signin_page.rs: blocked pages, cookie pick, redaction.
use super::*;

fn none() -> Hosts {
    Hosts::default()
}

fn test_hosts() -> Hosts {
    Hosts {
        test_origin: Some("http://127.0.0.1:5555".into()),
    }
}

#[test]
fn blocked_classifier() {
    let rej = "https://accounts.google.com/v3/signin/rejected?x=1";
    assert_eq!(blocked_signal(rej, ""), Some("rejected_page"));
    let ua = "https://accounts.google.com/o?error=disallowed_useragent";
    assert_eq!(blocked_signal(ua, ""), Some("disallowed_useragent"));
    // A title alone saying "Couldn't sign you in" is not enough (the daemon agrees).
    assert_eq!(
        blocked_signal("https://x/", "Couldn\u{2019}t sign you in"),
        None
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
    let b = format!("https://findplus-bridge.invalid/vault#{}", "a2V5cw");
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
fn classify_report_parts() {
    let u = "https://user@Accounts.Google.com:443/v3/signin/rejected?x=1#f";
    assert_eq!(
        host_and_path(u),
        ("accounts.google.com".into(), "/v3/signin/rejected".into())
    );
    assert_eq!(host_and_path("https://a.com"), ("a.com".into(), "/".into()));
    assert!(
        host_and_path(&format!("https://a.com/{}", "x".repeat(900)))
            .1
            .len()
            <= 512
    );
    assert_eq!(title_class(""), "unknown");
    assert_eq!(
        title_class("This browser or app may not be secure"),
        "browser_not_secure"
    );
    assert_eq!(
        title_class("Couldn\u{2019}t sign you in"),
        "couldnt_sign_in"
    );
    assert_eq!(title_class("Sign in - Google Accounts"), "normal");
    assert_eq!(fingerprint("a"), fingerprint("a"));
    assert_ne!(fingerprint("a"), fingerprint("b"));
}

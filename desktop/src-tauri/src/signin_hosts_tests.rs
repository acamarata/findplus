//! Unit tests for signin_hosts.rs: the allow-list table and the frame watch.
use super::*;

#[test]
fn google_sign_in_infrastructure_is_allowed() {
    for h in [
        "accounts.google.com",
        "myaccount.google.com",
        "www.google.com",
        "google.com",
        "consent.google.com",
        "ogs.google.com",
        "play.google.com",
        "apis.google.com",
        "www.google.de",
        "google.de",
        "consent.google.de",
        "accounts.google.de",
        "accounts.google.co.uk",
        "www.google.co.uk",
        "consent.google.com.br",
        "google.com.au",
        "ssl.gstatic.com",
        "www.gstatic.com",
        "fonts.gstatic.com",
        "gstatic.com",
        "fonts.googleapis.com",
        "content-autofill.googleapis.com",
        "lh3.googleusercontent.com",
        "www.recaptcha.net",
        "recaptcha.net",
        "accounts.youtube.com",
        "xn--80ak6aa92e.google.com",
    ] {
        assert!(is_allowed_host(h), "{h} should be allowed");
    }
}

#[test]
fn look_alikes_and_tricks_are_refused() {
    for h in [
        "",
        "google",
        "evilgoogle.com",
        "google.com.evil.net",
        "accounts.google.com.evil.net",
        "accounts.google.evil.com",
        "accounts.google.co.evil",
        "accounts.google.c",
        "google.evil",
        "google.co.uk.evil.de",
        "evil.de",
        "notgstatic.com",
        "gstatic.com.evil.io",
        "googleapis.com.evil.io",
        "recaptcha.net.evil.io",
        "youtube.com",
        "www.youtube.com",
        "accounts.youtube.com.evil.io",
        "accounts.google.com.",
        "accounts..google.com",
        ".google.com",
        "-x.google.com",
        "x-.google.com",
        "ACCOUNTS.GOOGLE.COM",
        "accounts.gооgle.com",
        "xn--ggle-0nda.com",
        "127.0.0.1",
        "1.2.3.4",
        "localhost",
        "[::1]",
        "google.com:8443",
        "login.microsoftonline.com",
        "okta.com",
    ] {
        assert!(!is_allowed_host(h), "{h} should be refused");
    }
}

#[test]
fn the_authority_must_be_a_bare_host() {
    for ok in [
        "https://accounts.google.com/",
        "https://accounts.google.com",
        "https://www.google.de/x?y=1#z",
    ] {
        assert!(authority_is_plain(ok), "{ok}");
    }
    for bad in [
        "https://accounts.google.com@evil.com/",
        "https://user:pw@accounts.google.com/",
        "https://accounts.google.com:8443/",
        "https://accounts.google.com:443/",
        "https:///nohost",
        "nonsense",
    ] {
        assert!(!authority_is_plain(bad), "{bad}");
    }
}

#[test]
fn a_frame_while_the_page_loads_never_counts() {
    let mut w = FrameWatch::default();
    w.committed();
    assert!(!w.refused_outside("ads.example.net", 0));
    assert_eq!(w.left_google(10_000), None);
    w.finished();
    assert_eq!(w.left_google(20_000), None);
}

#[test]
fn a_refusal_at_rest_counts_after_the_grace() {
    let mut w = FrameWatch::default();
    w.committed();
    w.finished();
    assert!(w.refused_outside("login.microsoftonline.com", 1_000));
    assert_eq!(w.left_google(1_000 + OUTSIDE_GRACE_MS - 1), None);
    assert_eq!(
        w.left_google(1_000 + OUTSIDE_GRACE_MS),
        Some("login.microsoftonline.com".into())
    );
    assert_eq!(w.left_google(99_000), None, "reported once");
}

#[test]
fn a_new_main_frame_page_clears_a_candidate() {
    let mut w = FrameWatch::default();
    w.finished();
    assert!(w.refused_outside("tracker.example.net", 0));
    w.committed();
    assert_eq!(w.left_google(60_000), None);
}

#[test]
fn before_the_first_page_a_refusal_is_a_candidate() {
    // The start page itself redirected off Google (a main-frame redirect).
    let mut w = FrameWatch::default();
    assert!(w.refused_outside("idp.example.org", 5));
    assert_eq!(
        w.left_google(5 + OUTSIDE_GRACE_MS),
        Some("idp.example.org".into())
    );
}

#[test]
fn the_first_candidate_is_kept() {
    let mut w = FrameWatch::default();
    w.refused_outside("first.example.org", 0);
    w.refused_outside("second.example.org", 1_000);
    assert_eq!(
        w.left_google(OUTSIDE_GRACE_MS),
        Some("first.example.org".into())
    );
}

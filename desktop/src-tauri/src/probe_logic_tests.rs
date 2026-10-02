//! Tests for probe_logic.rs: no network, no window, no real cookie values.

use super::*;

fn facts(url: &str, title: &str, cookie: Option<usize>) -> ProbeFacts {
    ProbeFacts {
        trail: vec!["accounts.google.com/EmbeddedSetup".into(), redact(url)],
        final_url: url.into(),
        final_title: title.into(),
        page_text_rejected: None,
        blocked_hosts: vec![],
        cookie_len: cookie,
        user_agent: "UA-TEST".into(),
        seconds: 42,
        fake_server: false,
    }
}

#[test]
fn allow_list_accepts_google_https_only() {
    assert!(allow_navigation("https", "accounts.google.com", false));
    assert!(!allow_navigation("http", "accounts.google.com", false));
    assert!(!allow_navigation("https", "evil.example", false));
    assert!(!allow_navigation("https", "accounts.google.com.evil.example", false));
    assert!(!allow_navigation("http", "127.0.0.1", false));
    assert!(allow_navigation("http", "127.0.0.1", true));
    assert!(!allow_navigation("https", "127.0.0.1", true));
}

#[test]
fn redact_drops_query_fragment_and_long_ids() {
    assert_eq!(
        redact("https://accounts.google.com/v3/signin/challenge/pwd?TL=abc&email=a@b.c#x"),
        "accounts.google.com/v3/signin/challenge/pwd"
    );
    let long = "x".repeat(40);
    assert_eq!(redact(&format!("https://h.test/a/{long}")), "h.test/a/<long>");
    assert_eq!(redact("https://h.test"), "h.test/");
}

#[test]
fn rejection_by_path_query_and_title() {
    assert!(rejection_signal("https://accounts.google.com/v3/signin/rejected", "").is_some());
    assert!(rejection_signal("https://a.google.com/x?error=disallowed_useragent", "").is_some());
    let s = rejection_signal("https://a.google.com/x", "Couldn't sign you in").unwrap();
    assert!(s.contains("title"));
    assert!(rejection_signal("https://a.google.com/x", "This browser or app may not be secure").is_some());
    assert!(rejection_signal("https://a.google.com/signin", "Sign in - Google Accounts").is_none());
}

#[test]
fn classify_orders_rejection_before_cookie() {
    let ok = "https://accounts.google.com/EmbeddedSetup";
    assert_eq!(classify(ok, "Sign in", true, false), Verdict::SignedIn);
    assert_eq!(classify(ok, "Sign in", false, false), Verdict::Unknown);
    assert_eq!(classify(ok, "Sign in", true, true), Verdict::Rejected);
    let rej = "https://accounts.google.com/v3/signin/rejected";
    assert_eq!(classify(rej, "x", true, false), Verdict::Rejected);
}

#[test]
fn cookie_picker_uses_name_only_and_returns_length() {
    let c = |n: &str, l| CookieInfo { name: n.into(), domain: ".google.com".into(), value_len: l };
    assert_eq!(find_oauth_token(&[c("SID", 5), c("oauth_token", 77)]), Some(77));
    assert_eq!(find_oauth_token(&[c("oauth_token2", 5), c("SID", 9)]), None);
    assert_eq!(find_oauth_token(&[]), None);
}

#[test]
fn trail_skips_repeats_and_caps() {
    let mut t = vec![];
    push_trail(&mut t, "a/".into());
    push_trail(&mut t, "a/".into());
    assert_eq!(t.len(), 1);
    for i in 0..100 {
        push_trail(&mut t, format!("h/{i}"));
    }
    assert_eq!(t.len(), 40);
}

#[test]
fn report_says_the_plain_facts_and_no_query() {
    let f = facts("https://myaccount.google.com/?secret=SHOULDNOTAPPEAR", "Google Account", Some(112));
    let r = report_text(&f);
    assert!(r.contains("SIGNED IN"));
    assert!(r.contains("Ended on: myaccount.google.com/"));
    assert!(r.contains("oauth_token cookie: YES (length 112, value not recorded)"));
    assert!(r.contains("User agent: UA-TEST"));
    assert!(r.contains("Time: 42 seconds"));
    assert!(!r.contains("SHOULDNOTAPPEAR"));
    assert!(r.contains("none seen in URL or title"));
}

#[test]
fn report_for_rejection_and_no_cookie() {
    let mut f = facts("https://accounts.google.com/v3/signin/rejected", "Couldn't sign you in", None);
    f.fake_server = true;
    f.blocked_hosts = vec!["evil.example".into()];
    let r = report_text(&f);
    assert!(r.contains("REJECTED"));
    assert!(r.contains("Rejection: YES, URL path is /signin/rejected"));
    assert!(r.contains("oauth_token cookie: NO"));
    assert!(r.contains("fake server"));
    assert!(r.contains("Blocked by allow-list: evil.example"));
}

#[test]
fn page_text_rejection_is_reported_when_url_and_title_are_clean() {
    let mut f = facts("https://accounts.google.com/x", "Sign in", None);
    f.page_text_rejected = Some(true);
    let r = report_text(&f);
    assert!(r.contains("REJECTED"));
    assert!(r.contains("page text mentions"));
}

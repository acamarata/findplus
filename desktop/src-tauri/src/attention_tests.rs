//! Unit tests for attention.rs: parsing, transitions, banner text, deep-link gate.
use super::*;
use serde_json::json;

fn body(google: Value, apple: Value) -> Value {
    json!({"providers": [
        {"id": "google-find-hub", "signed_in": false, "needs": [], "attention": google},
        {"id": "apple-find-my", "signed_in": false, "needs": [], "attention": apple},
    ]})
}

#[test]
fn parses_the_attention_field() {
    let a = parse(&body(json!("reauth"), json!("none"))).unwrap();
    assert_eq!(
        a,
        Attention {
            google: Some(Need::Signin),
            apple: None
        }
    );
    let a = parse(&body(json!("unlock"), json!("reauth"))).unwrap();
    assert_eq!(
        a,
        Attention {
            google: Some(Need::Unlock),
            apple: Some(Need::Signin)
        }
    );
    assert_eq!(parse(&json!({"http_status": 401})), None);
}

#[test]
fn falls_back_to_needs_on_an_older_daemon() {
    let old = json!({"providers": [{"id": "google-find-hub", "needs": ["chrome", "reauth"]}]});
    assert_eq!(parse(&old).unwrap().google, Some(Need::Signin));
    let old = json!({"providers": [{"id": "google-find-hub", "needs": ["shared_key"]}]});
    assert_eq!(parse(&old).unwrap().google, Some(Need::Unlock));
    let old = json!({"providers": [{"id": "google-find-hub", "needs": ["chrome"]}]});
    assert_eq!(parse(&old).unwrap().google, None);
    // An explicit null wins over `needs`: the new daemon has decided.
    let new =
        json!({"providers": [{"id": "google-find-hub", "needs": ["reauth"], "attention": null}]});
    assert_eq!(parse(&new).unwrap().google, None);
}

#[test]
fn one_banner_per_loss() {
    let healthy = Attention::default();
    let lost = Attention {
        google: Some(Need::Signin),
        apple: None,
    };
    assert_eq!(
        newly_needing(&healthy, &lost),
        vec![(Provider::Google, Need::Signin)]
    );
    // Still lost on the next poll: no second banner.
    assert!(newly_needing(&lost, &lost).is_empty());
    // Signin -> unlock is the same loss continuing, not a new one.
    let unlock = Attention {
        google: Some(Need::Unlock),
        apple: None,
    };
    assert!(newly_needing(&lost, &unlock).is_empty());
    // Healthy again, then lost again: a new banner.
    assert_eq!(newly_needing(&healthy, &unlock).len(), 1);
}

#[test]
fn banner_text_is_generic() {
    for (p, n) in [
        (Provider::Google, Need::Signin),
        (Provider::Google, Need::Unlock),
        (Provider::Apple, Need::Signin),
    ] {
        let (title, body) = banner(p, n);
        assert_eq!(title, "Find+ needs you");
        assert!(body.contains("menu bar icon"));
        assert!(!body.contains('@') && !body.contains('\u{2014}'));
    }
}

#[test]
fn deep_links_open_only_while_attention_is_set() {
    use Need::{Signin as S, Unlock as U};
    use Provider::{Apple as A, Google as G};
    assert_eq!(gate(G, S, None, false), Gate::Settings);
    assert_eq!(gate(G, S, Some(S), false), Gate::Open(S));
    assert_eq!(gate(G, U, Some(U), false), Gate::Open(U));
    // A link for the other need does not open: contract deep_links[url].
    assert_eq!(gate(G, S, Some(U), false), Gate::Settings);
    assert_eq!(gate(G, U, Some(S), false), Gate::Settings);
    assert_eq!(gate(A, S, Some(S), false), Gate::Open(S));
    assert_eq!(gate(A, S, None, false), Gate::Settings);
    // Locked: every link opens Settings (the lock screen first).
    assert_eq!(gate(G, S, Some(S), true), Gate::Settings);
}

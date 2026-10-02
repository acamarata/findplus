//! Unit tests for signin_http.rs parsing and error messages (no network).
use super::*;

fn none() -> Hosts {
    Hosts::default()
}

#[test]
fn begin_reply_parses_and_rejects_empty_state() {
    let url = "https://accounts.google.com/encryption/unlock/android?kdi=x";
    let b = parse_begin(&json!({"state": "s1", "unlock_url": url}), &none()).unwrap();
    assert_eq!(
        b,
        Begin {
            state: "s1".into(),
            unlock_url: Some(url.into())
        }
    );
    assert!(parse_begin(&json!({"state": ""}), &none()).is_none());
    assert!(parse_begin(&json!({}), &none()).is_none());
    assert!(parse_begin(&json!({"state": "x".repeat(300)}), &none()).is_none());
    let null_url = parse_begin(&json!({"state": "s", "unlock_url": null}), &none()).unwrap();
    assert_eq!(null_url.unlock_url, None);
}

#[test]
fn unlock_url_must_be_googles_unlock_page() {
    let h = none();
    assert!(valid_unlock_url(
        "https://accounts.google.com/encryption/unlock/android?kdi=x",
        &h
    ));
    for bad in [
        "https://accounts.google.com/EmbeddedSetup",
        "https://evil.com/encryption/unlock/android",
        "http://accounts.google.com/encryption/unlock/android",
        "http://127.0.0.1:5555/encryption/unlock/android",
        "javascript:alert(1)",
    ] {
        assert!(!valid_unlock_url(bad, &h), "{bad}");
    }
    let test = Hosts {
        test_origin: Some("http://127.0.0.1:5555".into()),
    };
    assert!(valid_unlock_url(
        "http://127.0.0.1:5555/encryption/unlock/android",
        &test
    ));
    // A card-supplied begin with a foreign unlock URL keeps the state, drops the URL.
    let b = parse_begin(
        &json!({"state": "s", "unlock_url": "https://evil.com/encryption/unlock/x"}),
        &h,
    );
    assert_eq!(b.unwrap().unlock_url, None);
}

#[test]
fn token_reply_defaults_to_no_unlock() {
    let r =
        parse_token(&json!({"result": "signed_in", "account": "a@b.com", "needs_unlock": true}));
    assert_eq!(
        r,
        TokenReply {
            account: Some("a@b.com".into()),
            needs_unlock: true
        }
    );
    assert_eq!(
        parse_token(&json!({})),
        TokenReply {
            account: None,
            needs_unlock: false
        }
    );
}

#[test]
fn errors_carry_the_code_and_never_a_credential() {
    let locked = api_error(401, &Value::Null);
    assert_eq!((locked.status, locked.message.as_str()), (401, MSG_LOCKED));
    let leak = api_error(
        400,
        &json!({"detail": "bad token oauth2_4/abc", "code": "token_rejected"}),
    );
    assert!(!leak.message.contains("oauth2_4"));
    assert_eq!(leak.code, "token_rejected");
    let ok = api_error(
        409,
        &json!({"detail": "Sign in to Google first.", "code": "not_signed_in"}),
    );
    assert_eq!(ok.message, "Sign in to Google first.");
    assert!(api_error(500, &Value::Null).message.contains("500"));
}

#[test]
fn the_progress_phase_is_read_plainly() {
    assert_eq!(
        parse_phase(&json!({"phase": "cancelled", "message": "x"})),
        Some("cancelled".into())
    );
    assert_eq!(parse_phase(&json!({"phase": 3})), None);
    assert_eq!(parse_phase(&Value::Null), None);
}

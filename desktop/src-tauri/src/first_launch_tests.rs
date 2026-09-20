use super::*;

#[test]
fn locked_stays_tray_only() {
    assert!(!decide(&serde_json::json!({}), Some(401)));
}

#[test]
fn completed_stays_tray_only() {
    let body = serde_json::json!({"onboarding.completed_at": "2026-09-20T00:00:00Z"});
    assert!(!decide(&body, Some(200)));
}

#[test]
fn incomplete_opens_window() {
    let body = serde_json::json!({"onboarding.completed_at": null});
    assert!(decide(&body, Some(200)));
}

#[test]
fn missing_field_opens_window() {
    // A settings payload from before this field existed cannot mean "finished",
    // so it falls toward showing the wizard rather than hiding it.
    assert!(decide(&serde_json::json!({}), Some(200)));
}

#[test]
fn timeout_stays_tray_only() {
    assert!(!decide(&serde_json::json!({}), None));
}

#[test]
fn non_200_stays_tray_only() {
    assert!(!decide(&serde_json::json!({}), Some(500)));
}

#[test]
fn malformed_body_on_200_is_treated_as_never_onboarded() {
    // resp.json() failing gives Value::Null, which has no key at all.
    assert!(decide(&serde_json::Value::Null, Some(200)));
}

#[test]
fn the_key_is_dotted_not_nested() {
    // A nested {"onboarding": {"completed_at": ...}} shape must NOT be read as
    // a completion: the wire contract is one flat dotted key (ruling F6).
    let nested = serde_json::json!({"onboarding": {"completed_at": "2026-09-20T00:00:00Z"}});
    assert!(decide(&nested, Some(200)));
}

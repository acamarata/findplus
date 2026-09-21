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
    let body = serde_json::json!({"onboarding.last_step": "welcome", "onboarding.completed_at": null});
    assert!(decide(&body, Some(200)));
}

#[test]
fn missing_field_stays_tray_only() {
    // A settings payload lacking any onboarding keys is treated as malformed/legacy.
    assert!(!decide(&serde_json::json!({}), Some(200)));
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
fn malformed_body_on_200_stays_tray_only() {
    // resp.json() failing gives Value::Null, which is not an object.
    assert!(!decide(&serde_json::Value::Null, Some(200)));
}

#[test]
fn the_key_is_dotted_not_nested() {
    // A nested {"onboarding": {"completed_at": ...}} shape lacks dotted keys
    // starting with "onboarding.", so it is rejected as malformed.
    let nested = serde_json::json!({"onboarding": {"completed_at": "2026-09-20T00:00:00Z"}});
    assert!(!decide(&nested, Some(200)));
}

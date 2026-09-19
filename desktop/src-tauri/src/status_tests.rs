use super::*;

#[test]
fn down_when_probe_failed() {
    let s = from_api(&serde_json::json!({"http_status": 0}), 5);
    assert_eq!(s.state, DotState::Down);
    assert_eq!(dot_color(&DotState::Down), DotColor::Grey);
}

#[test]
fn locked_on_401() {
    let s = from_api(&serde_json::json!({"http_status": 401}), 5);
    assert_eq!(s.state, DotState::Locked);
    assert_eq!(dot_color(&DotState::Locked), DotColor::Grey);
}

#[test]
fn error_on_auth_failure() {
    let s = from_api(&serde_json::json!({"last_error_type": "auth"}), 5);
    assert_eq!(s.state, DotState::Error);
    assert_eq!(s.line, "Sign-in needed");
}

#[test]
fn error_on_three_consecutive_failures() {
    let s = from_api(&serde_json::json!({"consecutive_failures": 3}), 5);
    assert_eq!(s.state, DotState::Error);
}

#[test]
fn stale_at_exactly_2x_plus_1s_not_at_2x() {
    let now = now_epoch();
    let exactly_2x = now - 2 * 5 * 60;
    let json_exact = serde_json::json!({"last_poll_at": epoch_to_iso(exactly_2x)});
    assert_eq!(from_api(&json_exact, 5).state, DotState::Ok);

    let over_2x = now - (2 * 5 * 60 + 1);
    let json_over = serde_json::json!({"last_poll_at": epoch_to_iso(over_2x)});
    assert_eq!(from_api(&json_over, 5).state, DotState::Stale);
}

fn epoch_to_iso(epoch: i64) -> String {
    // Inverse of parse_iso, good enough for round-trip in tests.
    let days = epoch.div_euclid(86400);
    let rem = epoch.rem_euclid(86400);
    let (h, mi, se) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    let jdn = days + 2440588;
    let a = jdn + 32044;
    let b = (4 * a + 3) / 146097;
    let c = a - (146097 * b) / 4;
    let d = (4 * c + 3) / 1461;
    let e = c - (1461 * d) / 4;
    let m = (5 * e + 2) / 153;
    let day = e - (153 * m + 2) / 5 + 1;
    let month = m + 3 - 12 * (m / 10);
    let year = 100 * b + d - 4800 + m / 10;
    format!("{year:04}-{month:02}-{day:02}T{h:02}:{mi:02}:{se:02}Z")
}

#[test]
fn ok_line_carries_the_next_poll_segment() {
    let now = now_epoch();
    let json = serde_json::json!({
        "last_poll_at": epoch_to_iso(now - 120),
        "next_poll_at": epoch_to_iso(now + 180),
    });
    let s = from_api(&json, 5);
    assert_eq!(s.state, DotState::Ok);
    assert!(
        s.line.starts_with("Polling normally · last poll 2m ago"),
        "{}",
        s.line
    );
    assert!(s.line.ends_with("· next in 4 min"), "{}", s.line);
}

#[test]
fn ok_line_omits_next_poll_when_the_daemon_reports_none() {
    let json = serde_json::json!({"last_poll_at": epoch_to_iso(now_epoch() - 60)});
    assert!(!from_api(&json, 5).line.contains("next in"));
}

#[test]
fn stale_follows_the_daemons_own_interval_not_a_hardcoded_five() {
    // 25 min old: stale at a 5-minute interval, still fine at a 60-minute one.
    let json = serde_json::json!({"last_poll_at": epoch_to_iso(now_epoch() - 25 * 60)});
    assert_eq!(from_api(&json, 5).state, DotState::Stale);
    assert_eq!(from_api(&json, 60).state, DotState::Ok);
}

//! Unit tests for notify.rs's pure decision functions.
//!
//! The network helpers are exercised against a real loopback socket in E8-T7;
//! everything here runs with no socket and no Tauri app handle.

use super::*;

fn row(id: u64, text: Option<&str>, body: Option<&str>) -> DeliveryRow {
    DeliveryRow {
        id,
        text: text.map(str::to_string),
        body: body.map(str::to_string),
    }
}

#[test]
fn next_cursor_advances_to_the_highest_row_id() {
    let rows = vec![row(3, None, None), row(9, None, None), row(7, None, None)];
    assert_eq!(next_cursor(0, &rows), 9);
}

#[test]
fn next_cursor_never_regresses_below_the_current_value() {
    assert_eq!(next_cursor(42, &[]), 42);
    assert_eq!(next_cursor(42, &[row(5, None, None)]), 42);
}

#[test]
fn should_process_is_true_only_for_200() {
    assert!(should_process(Some(200)));
}

#[test]
fn should_process_is_false_for_a_locked_401() {
    assert!(!should_process(Some(401)));
}

#[test]
fn should_process_is_false_when_the_daemon_is_down() {
    assert!(!should_process(None));
}

#[test]
fn a_delivery_row_deserializes_its_text_and_body() {
    let parsed: DeliveryRow =
        serde_json::from_str(r#"{"id":7,"channel":"native","text":"T","body":"B"}"#).unwrap();
    assert_eq!(parsed.id, 7);
    assert_eq!(parsed.text.as_deref(), Some("T"));
    assert_eq!(parsed.body.as_deref(), Some("B"));
}

#[test]
fn a_delivery_row_without_a_body_key_parses_to_none() {
    let parsed: DeliveryRow = serde_json::from_str(r#"{"id":7,"text":"T"}"#).unwrap();
    assert_eq!(parsed.body, None);
}

#[test]
fn locked_forces_the_generic_pair_even_with_detail_on() {
    assert_eq!(generic_pair(true, true), Some((GENERIC_TITLE, GENERIC_BODY)));
}

#[test]
fn detail_off_forces_the_generic_pair_even_when_unlocked() {
    assert_eq!(
        generic_pair(false, false),
        Some((GENERIC_TITLE, GENERIC_BODY))
    );
}

#[test]
fn unlocked_and_detail_on_shows_the_real_content() {
    assert_eq!(generic_pair(false, true), None);
}

#[test]
fn title_body_uses_the_generic_pair_when_one_is_given() {
    let (title, body) = title_body(
        &row(1, Some("Kid arrived at Home"), Some("Observed 14:00")),
        Some((GENERIC_TITLE, GENERIC_BODY)),
    );
    assert_eq!(title, GENERIC_TITLE);
    assert_eq!(body, GENERIC_BODY);
}

#[test]
fn title_body_uses_the_row_when_no_generic_pair_is_given() {
    let (title, body) = title_body(
        &row(1, Some("Kid arrived at Home"), Some("Observed 14:00")),
        None,
    );
    assert_eq!(title, "Kid arrived at Home");
    assert_eq!(body, "Observed 14:00");
}

#[test]
fn title_body_falls_back_to_generic_for_a_row_whose_event_was_pruned() {
    let (title, body) = title_body(&row(1, None, None), None);
    assert_eq!(title, GENERIC_TITLE);
    assert_eq!(body, GENERIC_BODY);
}

#[test]
fn title_body_tolerates_a_missing_body_on_a_detailed_row() {
    let (title, body) = title_body(&row(1, Some("Kid arrived at Home"), None), None);
    assert_eq!(title, "Kid arrived at Home");
    assert_eq!(body, "");
}

// ---------------------------------------------------------------------------
// Real-socket integration tests. The pure helpers above need no network; these
// drive the four HTTP functions against a one-shot TcpListener on an ephemeral
// port, so a broken URL, status mapping or fail-closed default shows up here
// rather than only in a running app.
// ---------------------------------------------------------------------------

use std::io::{Read, Write};
use std::net::TcpListener;

/// A listener that answers exactly one request with a fixed response, then ends.
/// `bind("127.0.0.1:0")` asks the OS for a fresh port per call, so tests in this
/// file can never collide on one.
fn fake_server(status_line: &'static str, body: &'static str) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    std::thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = stream.read(&mut buf);
            let resp = format!(
                "{status_line}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(resp.as_bytes());
        }
    });
    format!("http://{addr}")
}

/// Nothing listens on port 1 (reserved, and CI never runs as root), so a
/// connection there is refused immediately rather than after a 5 s timeout.
const REFUSED: &str = "http://127.0.0.1:1";

#[test]
fn fetch_deliveries_from_parses_a_real_200_response() {
    let base = fake_server(
        "HTTP/1.1 200 OK",
        r#"[{"id": 7, "channel": "native", "text": "Kid arrived at Home", "body": "Observed 14:00"}]"#,
    );
    let (status, rows) = fetch_deliveries_from(&base, 0);
    assert_eq!(status, Some(200));
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].id, 7);
    assert_eq!(rows[0].text.as_deref(), Some("Kid arrived at Home"));
}

#[test]
fn fetch_deliveries_from_treats_401_as_locked_not_success() {
    let base = fake_server("HTTP/1.1 401 Unauthorized", "{}");
    let (status, rows) = fetch_deliveries_from(&base, 0);
    assert_eq!(status, Some(401));
    assert!(rows.is_empty());
    assert!(!should_process(status));
}

#[test]
fn fetch_deliveries_from_returns_none_when_nothing_is_listening() {
    let (status, rows) = fetch_deliveries_from(REFUSED, 0);
    assert_eq!(status, None);
    assert!(rows.is_empty());
    assert!(!should_process(status));
}

#[test]
fn fetch_deliveries_from_yields_no_rows_for_a_body_that_will_not_parse() {
    let base = fake_server("HTTP/1.1 200 OK", "not json at all");
    let (status, rows) = fetch_deliveries_from(&base, 0);
    assert_eq!(status, Some(200));
    assert!(rows.is_empty());
}

#[test]
fn ack_at_posts_to_the_given_base_without_panicking() {
    let base = fake_server("HTTP/1.1 204 No Content", "");
    ack_at(&base, 7);
}

#[test]
fn ack_at_swallows_a_refused_connection() {
    ack_at(REFUSED, 7);
}

#[test]
fn fetch_locked_from_parses_a_real_locked_true_response() {
    let base = fake_server("HTTP/1.1 200 OK", r#"{"locked": true}"#);
    assert!(fetch_locked_from(&base));
}

#[test]
fn fetch_locked_from_parses_a_real_locked_false_response() {
    let base = fake_server("HTTP/1.1 200 OK", r#"{"locked": false}"#);
    assert!(!fetch_locked_from(&base));
}

#[test]
fn fetch_locked_from_fails_closed_on_connection_refused() {
    assert!(fetch_locked_from(REFUSED));
}

#[test]
fn fetch_locked_from_fails_closed_when_the_key_is_absent() {
    let base = fake_server("HTTP/1.1 200 OK", r#"{"something_else": false}"#);
    assert!(fetch_locked_from(&base));
}

#[test]
fn fetch_locked_from_fails_closed_on_a_non_200() {
    let base = fake_server("HTTP/1.1 500 Internal Server Error", "{}");
    assert!(fetch_locked_from(&base));
}

#[test]
fn fetch_native_detail_enabled_from_reads_the_dotted_setting() {
    let base = fake_server("HTTP/1.1 200 OK", r#"{"alerts.native_detail": true}"#);
    assert!(fetch_native_detail_enabled_from(&base));
}

#[test]
fn fetch_native_detail_enabled_from_fails_closed_on_connection_refused() {
    assert!(!fetch_native_detail_enabled_from(REFUSED));
}

#[test]
fn fetch_native_detail_enabled_from_fails_closed_when_the_key_is_absent() {
    let base = fake_server("HTTP/1.1 200 OK", r#"{"poll.interval_minutes": 5}"#);
    assert!(!fetch_native_detail_enabled_from(&base));
}

#[test]
fn a_refused_lock_check_still_forces_the_generic_pair() {
    // The two fail-closed defaults composed: this is what the poller actually
    // does when the daemon is unreachable mid-cycle.
    let locked = fetch_locked_from(REFUSED);
    let detail = if locked {
        false
    } else {
        fetch_native_detail_enabled_from(REFUSED)
    };
    assert_eq!(
        generic_pair(locked, detail),
        Some((GENERIC_TITLE, GENERIC_BODY))
    );
}

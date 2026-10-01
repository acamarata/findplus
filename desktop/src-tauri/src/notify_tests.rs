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
        status: Some("queued".to_string()),
    }
}

fn row_with_status(id: u64, status: Option<&str>) -> DeliveryRow {
    DeliveryRow {
        id,
        text: None,
        body: None,
        status: status.map(str::to_string),
    }
}

#[test]
fn only_a_queued_row_is_shown() {
    assert!(is_queued(&row_with_status(1, Some("queued"))));
}

#[test]
fn an_already_delivered_row_is_never_re_shown() {
    // The route filters by channel and cursor, not status, so a reset cursor
    // returns the whole native history; nothing already delivered may notify again.
    assert!(!is_queued(&row_with_status(1, Some("delivered"))));
}

#[test]
fn a_row_from_a_daemon_that_omits_status_is_treated_as_queued() {
    assert!(is_queued(&row_with_status(1, None)));
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

// ---------------------------------------------------------------------------
// Backoff (loop2 C2): next_poll_delay is the pure decision behind start()'s
// sleep duration.
// ---------------------------------------------------------------------------

#[test]
fn next_poll_delay_stays_at_the_base_on_success() {
    assert_eq!(
        next_poll_delay(Duration::from_secs(15), Some(200)),
        Duration::from_secs(15)
    );
}

#[test]
fn next_poll_delay_resets_to_the_base_when_locked() {
    // A 401 means the daemon answered; locked is normal operation, not a failure.
    assert_eq!(
        next_poll_delay(Duration::from_secs(60), Some(401)),
        Duration::from_secs(15)
    );
}

#[test]
fn next_poll_delay_doubles_on_each_unreachable_cycle_up_to_the_cap() {
    let d = next_poll_delay(Duration::from_secs(15), None);
    assert_eq!(d, Duration::from_secs(30));
    let d = next_poll_delay(d, None);
    assert_eq!(d, Duration::from_secs(60));
    // Capped, not doubled past it.
    let d = next_poll_delay(d, None);
    assert_eq!(d, Duration::from_secs(60));
}

#[test]
fn next_poll_delay_doubles_on_a_daemon_error_status_too() {
    assert_eq!(
        next_poll_delay(Duration::from_secs(15), Some(500)),
        Duration::from_secs(30)
    );
}

#[test]
fn next_poll_delay_never_produces_a_busy_loop_below_the_base() {
    // Defensive: a smaller-than-base starting delay should never happen in
    // practice, but the clamp must never let the next sleep go below 15s.
    assert_eq!(
        next_poll_delay(Duration::from_secs(1), None),
        Duration::from_secs(15)
    );
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

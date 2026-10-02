//! Unit tests for the pure event buffer in signin_events.rs (no Tauri app).

use super::*;
use serde_json::json;

fn names(v: &[(String, Value)]) -> Vec<&str> {
    v.iter().map(|(n, _)| n.as_str()).collect()
}

#[test]
fn a_page_that_is_not_ready_keeps_the_events_and_gets_them_once_ready() {
    let mut b = Buffer::default();
    let t = Instant::now();
    let load = b.loading();
    assert!(!b.offer("signin-apple-sheet", Value::Null, t));
    assert!(!b.offer("signin-result", json!({"outcome": "success"}), t));
    let out = b.ready(Some(load), t);
    assert_eq!(names(&out), ["signin-apple-sheet", "signin-result"]);
    assert!(b.ready(None, t).is_empty(), "replayed once only");
}

#[test]
fn only_the_last_event_of_each_kind_is_kept() {
    let mut b = Buffer::default();
    let t = Instant::now();
    b.offer("auth-attention", json!({"google": "signin"}), t);
    b.offer("signin-result", json!({"outcome": "cancelled"}), t);
    b.offer("auth-attention", json!({"google": null}), t);
    let out = b.ready(None, t);
    assert_eq!(names(&out), ["signin-result", "auth-attention"]);
    assert_eq!(out[1].1, json!({"google": null}));
}

#[test]
fn a_ready_page_gets_events_at_once() {
    let mut b = Buffer::default();
    let t = Instant::now();
    b.ready(None, t);
    assert!(b.offer("signin-result", Value::Null, t));
    assert!(b.offer("signin-apple-sheet", Value::Null, t));
    assert!(b.ready(None, t).is_empty());
}

#[test]
fn other_kinds_are_never_held_back() {
    let mut b = Buffer::default();
    let t = Instant::now();
    assert!(b.offer("signin-progress", Value::Null, t));
    assert!(b.ready(None, t).is_empty());
}

#[test]
fn a_reload_makes_the_page_not_ready_again() {
    let mut b = Buffer::default();
    let t = Instant::now();
    b.ready(None, t);
    b.loading();
    assert!(!b.offer("signin-apple-sheet", Value::Null, t));
    assert_eq!(names(&b.ready(None, t)), ["signin-apple-sheet"]);
}

#[test]
fn a_late_settle_timer_cannot_mark_a_newer_load_ready() {
    let mut b = Buffer::default();
    let t = Instant::now();
    let first = b.loading();
    let second = b.loading();
    b.offer("signin-apple-sheet", Value::Null, t);
    assert!(b.ready(Some(first), t).is_empty(), "stale timer ignored");
    assert_eq!(names(&b.ready(Some(second), t)), ["signin-apple-sheet"]);
}

#[test]
fn the_settle_timer_does_nothing_after_the_page_said_ready() {
    let mut b = Buffer::default();
    let t = Instant::now();
    let load = b.loading();
    b.offer("signin-result", Value::Null, t);
    assert_eq!(names(&b.ready(None, t)), ["signin-result"]);
    assert!(b.ready(Some(load), t).is_empty());
}

#[test]
fn an_old_event_is_dropped_not_replayed() {
    let mut b = Buffer::default();
    let then = Instant::now();
    b.offer("signin-apple-sheet", Value::Null, then);
    b.offer("signin-result", Value::Null, then + MAX_AGE);
    let out = b.ready(None, then + MAX_AGE + Duration::from_secs(1));
    assert_eq!(names(&out), ["signin-result"]);
}

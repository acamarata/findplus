//! Unit tests for signin_close.rs (pure parts only: no window, no Tauri app).

use super::*;
use crate::signin_machine::{step, Effect, Input, Outcome};

#[test]
fn a_request_is_taken_once_and_a_new_session_forgets_an_old_one() {
    // One test owns the global flag, so parallel tests cannot race on it.
    clear();
    assert!(!take_request());
    request();
    assert!(take_request());
    assert!(!take_request(), "taken once");
    request();
    clear();
    assert!(
        !take_request(),
        "a request from before the session is dropped"
    );
}

#[test]
fn the_daemon_cancel_closes_a_waiting_or_unlocking_window() {
    for mode in [Mode::Signin, Mode::Unlock] {
        assert!(daemon_says_stop(Phase::Waiting, mode, "cancelled"));
        assert!(daemon_says_stop(Phase::Unlocking, mode, "cancelled"));
    }
}

#[test]
fn signed_in_but_unlock_cancelled_closes_the_unlock_page() {
    assert!(daemon_says_stop(Phase::Unlocking, Mode::Signin, "success"));
    // Unlock-only mode: "success" can only come from this window's own keys.
    assert!(!daemon_says_stop(Phase::Unlocking, Mode::Unlock, "success"));
}

#[test]
fn ordinary_progress_never_closes_the_window() {
    for p in [
        "connecting",
        "waiting",
        "needs_unlock",
        "finishing",
        "error",
        "idle",
        "",
    ] {
        assert!(!daemon_says_stop(Phase::Waiting, Mode::Signin, p), "{p}");
        assert!(!daemon_says_stop(Phase::Unlocking, Mode::Signin, p), "{p}");
    }
    // A malformed cookie sets "error" while the window keeps waiting.
    assert!(!daemon_says_stop(Phase::Waiting, Mode::Signin, "error"));
}

#[test]
fn an_exchange_in_flight_is_never_interrupted() {
    for p in [Phase::Finishing, Phase::Storing, Phase::Done] {
        assert!(!daemon_says_stop(p, Mode::Signin, "cancelled"));
    }
}

#[test]
fn a_close_feeds_the_machine_a_user_close() {
    // What the session does with a stop: the same input as the window's own close.
    let (phase, effect) = step(Phase::Waiting, Mode::Signin, &Input::UserClosed);
    assert_eq!(phase, Phase::Done);
    assert_eq!(effect, Effect::Finish(Outcome::Cancelled));
    let (_, effect) = step(Phase::Unlocking, Mode::Signin, &Input::UserClosed);
    assert_eq!(effect, Effect::Finish(Outcome::Success { unlocked: false }));
}

#[test]
fn the_close_plan_follows_the_session_then_the_window() {
    assert_eq!(plan(true, true), CloseResult::Closing);
    assert_eq!(plan(true, false), CloseResult::Closing);
    assert_eq!(plan(false, true), CloseResult::Destroyed);
    assert_eq!(plan(false, false), CloseResult::NotOpen);
    assert_eq!(CloseResult::NotOpen.wire(), "not_open");
}

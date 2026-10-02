//! Unit tests for signin_machine.rs: every path through the sign-in window.
use super::*;
use Effect as E;
use Input as I;
use Outcome as O;
use Phase as P;

fn run(mode: Mode, inputs: &[I]) -> (P, Vec<E>) {
    let mut phase = P::Waiting;
    let mut effects = Vec::new();
    for i in inputs {
        let (p, e) = step(phase, mode, i);
        phase = p;
        effects.push(e);
    }
    (phase, effects)
}

fn accepted(needs_unlock: bool) -> I {
    I::TokenAccepted {
        needs_unlock,
        has_unlock_url: true,
    }
}

#[test]
fn sign_in_without_unlock() {
    let (p, e) = run(Mode::Signin, &[I::CookieFound, accepted(false)]);
    assert_eq!(p, P::Done);
    assert_eq!(
        e,
        vec![E::PostToken, E::Finish(O::Success { unlocked: true })]
    );
}

#[test]
fn sign_in_then_unlock_in_the_same_window() {
    let (p, e) = run(
        Mode::Signin,
        &[
            I::CookieFound,
            accepted(true),
            I::VaultKeys,
            I::UnlockStored,
        ],
    );
    assert_eq!(p, P::Done);
    assert_eq!(
        e,
        vec![
            E::PostToken,
            E::NavigateUnlock,
            E::PostUnlock,
            E::Finish(O::Success { unlocked: true })
        ]
    );
}

#[test]
fn needs_unlock_without_a_url_finishes_signed_in_but_locked() {
    let i = I::TokenAccepted {
        needs_unlock: true,
        has_unlock_url: false,
    };
    let (_, e) = run(Mode::Signin, &[I::CookieFound, i]);
    assert_eq!(e[1], E::Finish(O::Success { unlocked: false }));
}

#[test]
fn leaving_the_unlock_page_after_sign_in_still_counts_as_signed_in() {
    for end in [I::UserClosed, I::BridgeClose, I::TimedOut] {
        let (_, e) = run(Mode::Signin, &[I::CookieFound, accepted(true), end.clone()]);
        assert_eq!(e[2], E::Finish(O::Success { unlocked: false }), "{end:?}");
    }
}

#[test]
fn unlock_only_mode_waits_for_the_account_page() {
    let other = I::PageLoaded { blocked: false };
    let (p, e) = run(
        Mode::Unlock,
        &[
            I::CookieFound,
            other,
            I::AccountKnown,
            I::VaultKeys,
            I::UnlockStored,
        ],
    );
    assert_eq!(p, P::Done);
    assert_eq!(
        e,
        vec![
            E::None,
            E::None,
            E::NavigateUnlock,
            E::PostUnlock,
            E::Finish(O::Success { unlocked: true })
        ]
    );
    let (_, e) = run(Mode::Unlock, &[I::AccountKnown, I::BridgeClose]);
    assert_eq!(e[1], E::Finish(O::Cancelled));
    // Sign-in mode ignores the account message: the token names the account.
    assert_eq!(run(Mode::Signin, &[I::AccountKnown]).1[0], E::None);
}

#[test]
fn blocked_cancelled_timeout_error() {
    let blocked = I::PageLoaded { blocked: true };
    assert_eq!(
        run(Mode::Signin, &[blocked]).1[0],
        E::Finish(O::BlockedEmbedded)
    );
    assert_eq!(
        run(Mode::Signin, &[I::Blocked]).1[0],
        E::Finish(O::BlockedEmbedded)
    );
    assert_eq!(
        run(Mode::Signin, &[I::UserClosed]).1[0],
        E::Finish(O::Cancelled)
    );
    assert_eq!(
        run(Mode::Signin, &[I::TimedOut]).1[0],
        E::Finish(O::Timeout)
    );
    assert_eq!(run(Mode::Signin, &[I::Failed]).1[0], E::Finish(O::Error));
    let (_, e) = run(Mode::Signin, &[I::CookieFound, I::TokenRejected]);
    assert_eq!(e[1], E::Finish(O::Error));
    let (_, e) = run(
        Mode::Unlock,
        &[I::AccountKnown, I::VaultKeys, I::UnlockRejected],
    );
    assert_eq!(e[2], E::Finish(O::Error));
}

#[test]
fn done_is_terminal_and_nothing_runs_twice() {
    let (p, e) = run(
        Mode::Signin,
        &[
            I::CookieFound,
            accepted(false),
            I::CookieFound,
            I::UserClosed,
            I::TimedOut,
        ],
    );
    assert_eq!(p, P::Done);
    assert_eq!(&e[2..], &[E::None, E::None, E::None]);
}

#[test]
fn a_second_cookie_while_finishing_does_not_post_again() {
    let (_, e) = run(Mode::Signin, &[I::CookieFound, I::CookieFound]);
    assert_eq!(e, vec![E::PostToken, E::None]);
}

#[test]
fn wire_strings_are_the_contract() {
    assert_eq!(O::Success { unlocked: false }.wire(), "success");
    assert_eq!(O::BlockedEmbedded.wire(), "blocked_embedded");
    assert_eq!(O::Cancelled.wire(), "cancelled");
    assert_eq!(O::Timeout.wire(), "timeout");
    assert_eq!(O::Error.wire(), "error");
    assert_eq!(
        O::BlockedEmbedded.daemon_event(None),
        ("blocked", Some("other"))
    );
    let outside = O::BlockedEmbedded.daemon_event(Some("outside_google"));
    assert_eq!(outside, ("blocked", Some("outside_google")));
    assert_eq!(O::Timeout.daemon_event(None), ("failed", Some("timeout")));
    assert_eq!(O::Cancelled.daemon_event(Some("x")), ("closed", None));
    assert_eq!(O::Error.daemon_event(None), ("failed", Some("other")));
    assert_eq!(P::Unlocking.wire(), "unlock");
    assert_eq!(Mode::parse(None), Some(Mode::Signin));
    assert_eq!(Mode::parse(Some("unlock")), Some(Mode::Unlock));
    assert_eq!(Mode::parse(Some("x")), None);
}

#[test]
fn result_payload_shapes() {
    let ok = result_payload(
        Mode::Signin,
        O::Success { unlocked: true },
        Some("a@b.com"),
        None,
        None,
    );
    assert_eq!(
        ok,
        serde_json::json!({"provider": "google", "mode": "signin", "outcome": "success", "unlocked": true, "account": "a@b.com"})
    );
    let blocked = result_payload(
        Mode::Signin,
        O::BlockedEmbedded,
        None,
        None,
        Some("rejected_page"),
    );
    assert_eq!(blocked["reason"], "rejected_page");
    assert!(blocked.get("account").is_none());
    let err = result_payload(Mode::Unlock, O::Error, None, Some("Try again."), Some("x"));
    assert_eq!(err["message"], "Try again.");
    assert!(err.get("reason").is_none());
}

#[test]
fn token_refusals_follow_the_contract() {
    assert_eq!(token_retry("google_unreachable", false), TokenRetry::Now);
    assert_eq!(token_retry("google_unreachable", true), TokenRetry::Fail);
    assert_eq!(
        token_retry("token_malformed", true),
        TokenRetry::KeepPolling
    );
    for code in [
        "token_rejected",
        "state_invalid",
        "bad_client",
        "signin_failed",
        "",
    ] {
        assert_eq!(token_retry(code, false), TokenRetry::Fail, "{code}");
    }
    let (p, e) = run(
        Mode::Signin,
        &[I::CookieFound, I::TokenRetryLater, I::CookieFound],
    );
    assert_eq!(p, P::Finishing);
    assert_eq!(e, vec![E::PostToken, E::None, E::PostToken]);
}

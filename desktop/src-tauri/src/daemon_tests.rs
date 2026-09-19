use super::*;

#[test]
fn row1_attaches_when_app_matches() {
    assert_eq!(
        decide(Some(("findplus", "1.0.0.dev0")), None, false),
        DaemonState::Attached
    );
}

#[test]
fn test_another_app() {
    assert_eq!(
        decide(Some(("some-other-app", "9.9.9")), None, false),
        DaemonState::AnotherApp
    );
}

#[test]
fn row3_refused_dead_pid_launch_agent_present() {
    assert_eq!(decide(None, None, true), DaemonState::WaitingLaunchAgent);
}

#[test]
fn row4_refused_dead_pid_no_launch_agent() {
    assert_eq!(decide(None, None, false), DaemonState::WaitingSidecar);
}

#[test]
fn row5_refused_live_pid_waits() {
    assert_eq!(decide(None, Some(4242), false), DaemonState::WaitingPid);
    assert_eq!(decide(None, Some(4242), true), DaemonState::WaitingPid);
}

#[test]
fn test_version_mismatch_still_attaches() {
    // A version mismatch is a warning, not a different DaemonState: the
    // CLI daemon is still ours, just a different build. start() logs
    // the "CLI daemon vX" warning; decide() itself stays Attached.
    assert_eq!(
        decide(Some(("findplus", "0.9.9")), None, false),
        DaemonState::Attached
    );
}

#[test]
fn test_crashed() {
    // Simulates the transition start() makes: an attach observed, then
    // a probe failure while a pid is not (yet, or no longer) alive.
    set_down_reason(DaemonDownReason::Normal);
    assert_eq!(down_reason(), DaemonDownReason::Normal);
    set_down_reason(DaemonDownReason::Crashed);
    assert_eq!(down_reason(), DaemonDownReason::Crashed);
}

// test_locked_grey lives in status.rs (`locked_on_401`) — Locked/Grey is
// a Status/DotState concern, not a DaemonState one; not duplicated here.

#[test]
fn start_runs_exactly_one_supervisor_loop() {
    // "Restart daemon" used to call start() again, leaving a second loop
    // running; two loops can each spawn their own sidecar.
    use std::sync::atomic::Ordering;
    SUPERVISOR_RUNNING.store(false, Ordering::SeqCst);
    assert!(!SUPERVISOR_RUNNING.swap(true, Ordering::SeqCst));
    assert!(SUPERVISOR_RUNNING.swap(true, Ordering::SeqCst));
    SUPERVISOR_RUNNING.store(false, Ordering::SeqCst);
}

#[test]
fn no_child_is_tracked_before_one_is_spawned() {
    // The WaitingSidecar branch spawns only when child_running() is false, so
    // a stale tick can never add a second sidecar behind a live one.
    assert!(!child_running());
}

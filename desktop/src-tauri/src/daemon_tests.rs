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

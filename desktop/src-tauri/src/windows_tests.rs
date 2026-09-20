use super::*;

#[test]
fn attaches_when_the_port_is_ours() {
    assert!(may_attach(None));
}

#[test]
fn refuses_to_attach_to_a_port_squatter() {
    // daemon.rs sets this line on DaemonState::AnotherApp. Pointing a window
    // at that port would hand the app's remote capability to whatever is
    // listening (CR-C-E8 minor).
    assert!(!may_attach(Some("Port 8647 is used by another program")));
}

#[test]
fn any_another_app_line_refuses_not_just_the_known_wording() {
    assert!(!may_attach(Some("")));
    assert!(!may_attach(Some("something else has it")));
}

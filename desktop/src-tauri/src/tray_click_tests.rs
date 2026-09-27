use super::*;

#[test]
fn left_click_release_opens_the_dashboard() {
    assert!(opens_dashboard(MouseButton::Left, MouseButtonState::Up));
}

#[test]
fn left_click_press_does_not_open_yet() {
    // Only the release counts, so a press that turns into a drag off the
    // icon never opens a window.
    assert!(!opens_dashboard(MouseButton::Left, MouseButtonState::Down));
}

#[test]
fn right_click_never_opens_the_dashboard() {
    assert!(!opens_dashboard(MouseButton::Right, MouseButtonState::Up));
    assert!(!opens_dashboard(MouseButton::Right, MouseButtonState::Down));
}

#[test]
fn middle_click_never_opens_the_dashboard() {
    assert!(!opens_dashboard(MouseButton::Middle, MouseButtonState::Up));
    assert!(!opens_dashboard(
        MouseButton::Middle,
        MouseButtonState::Down
    ));
}

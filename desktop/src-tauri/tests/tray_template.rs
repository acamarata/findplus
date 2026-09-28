//! The tray glyph stays a macOS template image after every state change.
//!
//! Purpose    : Pin the 1.1.5 fix. `set_icon()` replaces the tray's NSImage and
//!              the replacement is not a template, so macOS drew the black
//!              "F+" glyph untinted: invisible on a dark menu bar. Every
//!              `set_icon` in the tray code must be followed by
//!              `set_icon_as_template(true)`.
//! Inputs     : src/tray.rs as text (the tray needs a live event loop).

const TRAY: &str = include_str!("../src/tray.rs");

#[test]
fn the_builder_marks_the_first_icon_as_a_template() {
    assert!(TRAY.contains(".icon_as_template(true)"));
}

#[test]
fn every_icon_swap_is_re_marked_as_a_template() {
    let swaps = TRAY.matches("tray.set_icon(").count();
    let remarks = TRAY.matches("tray.set_icon_as_template(true)").count();
    assert!(swaps > 0, "the tray should swap its icon when the state changes");
    assert_eq!(
        swaps, remarks,
        "each set_icon() needs a set_icon_as_template(true) after it"
    );
}

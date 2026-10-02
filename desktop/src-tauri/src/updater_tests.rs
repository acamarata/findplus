//! Pure updater decisions (updater_logic.rs): when to install, from where, how.

use std::path::Path;
use std::time::Duration;

use serde_json::json;

use super::logic::*;

fn ready() -> UpdateStatus {
    parse_status(&json!({"staged_version": "1.3.0", "auto_install_ready": true}))
}

#[test]
fn status_bodies_parse_and_missing_fields_mean_nothing_to_do() {
    assert_eq!(ready().staged_version.as_deref(), Some("1.3.0"));
    assert!(ready().auto_install_ready);
    assert_eq!(parse_status(&json!({})), UpdateStatus::default());
    assert_eq!(
        parse_status(&json!({"detail": "Locked"})),
        UpdateStatus::default()
    );
}

#[test]
fn installs_by_itself_only_when_ready_unused_and_not_paused() {
    let long = Duration::from_secs(6 * 60);
    assert!(should_auto_install(&ready(), false, long, false));
    assert!(!should_auto_install(
        &ready(),
        false,
        Duration::from_secs(60),
        false
    ));
    assert!(
        !should_auto_install(&ready(), true, long, false),
        "a window is open"
    );
    assert!(should_auto_install(&ready(), true, IDLE_VISIBLE, false));
    assert!(
        !should_auto_install(&ready(), false, long, true),
        "paused after a failure"
    );
    let off = parse_status(&json!({"staged_version": "1.3.0", "auto_install_ready": false}));
    assert!(
        !should_auto_install(&off, false, long, false),
        "switch off or attempt failed"
    );
    assert!(!should_auto_install(
        &UpdateStatus::default(),
        false,
        long,
        false
    ));
}

#[test]
fn only_an_installed_bundle_named_find_plus_updates() {
    let exe = Path::new("/Applications/Find+.app/Contents/MacOS/findplus");
    assert_eq!(
        bundle_parent(exe),
        Some(Path::new("/Applications").to_path_buf())
    );
    let user = Path::new("/Users/x/Applications/Find+.app/Contents/MacOS/findplus");
    assert_eq!(
        bundle_parent(user),
        Some(Path::new("/Users/x/Applications").to_path_buf())
    );
    assert_eq!(
        bundle_parent(Path::new("/repo/target/debug/findplus")),
        None
    );
    assert_eq!(
        bundle_parent(Path::new("/x/Other.app/Contents/MacOS/findplus")),
        None
    );
}

fn apply(kind: &str) -> Apply {
    parse_apply(
        200,
        &json!({"kind": kind, "path": "/u/FindPlus-1.3.0-aarch64.dmg", "version": "1.3.0",
                "result_file": "/u/last-result", "backup": "/b/x.sqlite"}),
    )
    .unwrap()
}

#[test]
fn apply_bodies_and_refusals() {
    assert_eq!(apply("dmg").version, "1.3.0");
    let refused = parse_apply(
        409,
        &json!({"detail": "There is no update ready to install."}),
    );
    assert_eq!(refused.unwrap_err(), "There is no update ready to install.");
    assert_eq!(
        parse_apply(500, &json!({})).unwrap_err(),
        "Find+ answered 500."
    );
    assert!(parse_apply(
        200,
        &json!({"kind": "zip", "path": "/x", "result_file": "/r"})
    )
    .is_err());
    assert!(parse_apply(200, &json!({"kind": "dmg", "path": "/x"})).is_err());
}

#[test]
fn the_script_verifies_first_then_waits_for_this_process() {
    let script = Path::new("/u/update-app.sh");
    let verify = script_args(script, &apply("dmg"), None);
    assert_eq!(
        verify,
        [
            "/u/update-app.sh",
            "--dmg",
            "/u/FindPlus-1.3.0-aarch64.dmg",
            "--verify-only"
        ]
    );
    let run = script_args(script, &apply("app"), Some(42));
    assert_eq!(
        &run[1..],
        [
            "--app",
            "/u/FindPlus-1.3.0-aarch64.dmg",
            "--wait-pid",
            "42",
            "--result",
            "/u/last-result"
        ]
    );
    assert!(
        !run.iter().any(|a| a == "--force"),
        "an automatic install never forces"
    );
}

#[test]
fn labels_and_reasons_are_short() {
    assert_eq!(tray_label("1.3.0"), "Restart to update (v1.3.0)");
    let out = "update: Find+ 1.2.1 -> 1.3.0\nupdate: the new app is signed by team X, not Y.\n\n";
    assert_eq!(last_line(out), "the new app is signed by team X, not Y.");
}

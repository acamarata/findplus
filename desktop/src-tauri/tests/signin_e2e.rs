//! End-to-end test of the in-app sign-in window against the fake server.
//!
//! Purpose    : Run the real app binary in its debug self-test mode
//!              (src/signin_selftest.rs): a real WKWebView sign-in window, a
//!              fake EmbeddedSetup/unlock/rejection site and a fake daemon on
//!              127.0.0.1. Checks the HttpOnly cookie is read, the token and
//!              vault keys reach the "daemon", the bridge works, and every
//!              outcome is reported.
//! Constraints: Opens a real (small) window for a few seconds, so it runs only
//!              when FINDPLUS_SIGNIN_E2E=1 (macOS, logged-in GUI session). No
//!              Google, no Chrome, no network beyond 127.0.0.1. Debug builds
//!              only: a release binary has no self-test mode.

use std::process::Command;

fn run_case(case: &str) -> serde_json::Value {
    let out = Command::new(env!("CARGO_BIN_EXE_findplus"))
        .env("FINDPLUS_SIGNIN_SELFTEST", case)
        .env("FINDPLUS_NO_LAUNCH", "1")
        .output()
        .expect("run the app binary");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let line = stdout
        .lines()
        .find_map(|l| l.strip_prefix("SIGNIN-RESULT "))
        .unwrap_or_else(|| panic!("{case}: no result line in {stdout}"));
    assert!(!stdout.contains("oauth2_4/"), "{case}: token printed");
    assert!(!stdout.contains("vault"), "{case}: vault keys printed");
    serde_json::from_str(line).expect("result JSON")
}

#[test]
fn signin_window_end_to_end() {
    if std::env::var("FINDPLUS_SIGNIN_E2E").as_deref() != Ok("1") || !cfg!(debug_assertions) {
        eprintln!("skipped: set FINDPLUS_SIGNIN_E2E=1 (debug build, macOS GUI session)");
        return;
    }
    let r = run_case("ok");
    assert_eq!(r["outcome"], "success", "{r}");
    assert_eq!(r["unlocked"], true, "{r}");
    assert_eq!(r["account"], "fake@example.com", "{r}");

    let r = run_case("handed");
    assert_eq!(r["outcome"], "success", "{r}");
    assert_eq!(r["unlocked"], true, "{r}");

    let r = run_case("unlock");
    assert_eq!(r["outcome"], "success", "{r}");
    assert_eq!(r["mode"], "unlock", "{r}");
    assert_eq!(r["unlocked"], true, "{r}");

    let r = run_case("reject");
    assert_eq!(r["outcome"], "blocked_embedded", "{r}");

    let r = run_case("cancel");
    assert_eq!(r["outcome"], "cancelled", "{r}");
}

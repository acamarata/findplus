//! Guard for "Google's page in the sign-in window cannot call any Tauri
//! command" (signin_window.rs, spec §9.1; r12 #7).
//!
//! Purpose    : The claim rests on Tauri's ACL: a webview reaches a command
//!              only through a capability that names its window. These tests
//!              read the real capability files, tauri.conf.json and build.rs,
//!              and fail if any capability (by name or by glob) could apply to
//!              the sign-in window, if a remote URL in one names a Google
//!              host, or if a sign-in command stops refusing callers other
//!              than `main`.
//! Constraints: Text and JSON only: no Tauri app, no window.

use std::path::{Path, PathBuf};

use crate::signin_window::LABEL;

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf()
}

/// Tauri's window patterns are globs; `*` matches any run of characters.
fn glob_match(pattern: &str, label: &str) -> bool {
    match pattern.split_once('*') {
        None => pattern == label,
        Some((head, rest)) => {
            let Some(tail) = label.strip_prefix(head) else {
                return false;
            };
            (0..=tail.len()).any(|i| tail.is_char_boundary(i) && glob_match(rest, &tail[i..]))
        }
    }
}

fn capabilities() -> Vec<(PathBuf, serde_json::Value)> {
    let dir = root().join("capabilities");
    let mut out = Vec::new();
    for entry in std::fs::read_dir(dir).unwrap().flatten() {
        let path = entry.path();
        let text = std::fs::read_to_string(&path).unwrap();
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        assert_eq!(
            ext, "json",
            "{path:?}: only JSON capabilities are checked here"
        );
        out.push((path, serde_json::from_str(&text).unwrap()));
    }
    assert!(!out.is_empty());
    out
}

fn strings(v: &serde_json::Value) -> Vec<String> {
    let list = v.as_array().cloned().unwrap_or_default();
    list.iter()
        .map(|s| s.as_str().unwrap_or("").to_string())
        .collect()
}

#[test]
fn the_glob_matcher_follows_tauri() {
    assert!(glob_match("*", LABEL));
    assert!(glob_match("signin-*", LABEL));
    assert!(glob_match("*google", LABEL));
    assert!(glob_match(LABEL, LABEL));
    assert!(!glob_match("main", LABEL));
    assert!(!glob_match("main*", LABEL));
}

#[test]
fn no_capability_applies_to_the_signin_window() {
    for (path, cap) in capabilities() {
        let windows = strings(&cap["windows"]);
        let webviews = strings(&cap["webviews"]);
        assert!(
            !windows.is_empty() || !webviews.is_empty(),
            "{path:?}: a capability with no window list must not exist"
        );
        for pattern in windows.iter().chain(webviews.iter()) {
            assert!(
                !glob_match(pattern, LABEL),
                "{path:?}: {pattern} matches {LABEL}"
            );
        }
        for url in strings(&cap["remote"]["urls"]) {
            let lower = url.to_lowercase();
            for bad in [
                "google",
                "gstatic",
                "recaptcha",
                "youtube",
                "https://*",
                "*://",
            ] {
                assert!(!lower.contains(bad), "{path:?}: remote URL {url}");
            }
        }
    }
}

#[test]
fn the_config_adds_no_inline_capability_or_signin_window() {
    let text = std::fs::read_to_string(root().join("tauri.conf.json")).unwrap();
    let conf: serde_json::Value = serde_json::from_str(&text).unwrap();
    let inline = &conf["app"]["security"]["capabilities"];
    for cap in inline.as_array().cloned().unwrap_or_default() {
        assert!(
            cap.is_string(),
            "inline capability object in tauri.conf.json"
        );
    }
    for w in conf["app"]["windows"]
        .as_array()
        .cloned()
        .unwrap_or_default()
    {
        assert_ne!(w["label"].as_str(), Some(LABEL));
    }
}

/// The quoted names in build.rs's APP_COMMANDS list.
fn app_commands() -> Vec<String> {
    let build = std::fs::read_to_string(root().join("build.rs")).unwrap();
    let start = build
        .find("const APP_COMMANDS")
        .expect("APP_COMMANDS in build.rs");
    let list = &build[start..start + build[start..].find("];").unwrap()];
    list.split('"')
        .skip(1)
        .step_by(2)
        .map(String::from)
        .collect()
}

/// The body of `pub fn <name>(` in src/, from the signature to its closing brace.
fn command_body(name: &str) -> String {
    for entry in std::fs::read_dir(root().join("src")).unwrap().flatten() {
        let text = std::fs::read_to_string(entry.path()).unwrap_or_default();
        if let Some(at) = text.find(&format!("pub fn {name}(")) {
            let head = text[..at].trim_end();
            assert!(
                head.ends_with("#[tauri::command]") || head.ends_with("#[tauri::command(async)]"),
                "{name} is not a command"
            );
            let body = &text[at..];
            return body[..body.find("\n}\n").unwrap_or(body.len())].to_string();
        }
    }
    panic!("command {name} not found in src/");
}

#[test]
fn every_permission_granted_is_an_app_command() {
    let commands = app_commands();
    for (path, cap) in capabilities() {
        for perm in strings(&cap["permissions"]) {
            if let Some(cmd) = perm.strip_prefix("allow-") {
                let cmd = cmd.replace('-', "_");
                assert!(
                    commands.contains(&cmd),
                    "{path:?}: {perm} is not an app command"
                );
            }
        }
    }
}

#[test]
fn the_signin_commands_refuse_any_caller_but_main() {
    let commands = app_commands();
    for name in ["open_signin_window", "close_signin_window", "webview_ready", "apply_update"] {
        assert!(
            commands.iter().any(|c| c == name),
            "{name} missing from build.rs"
        );
        let body = command_body(name);
        let guard = body
            .find("if webview.label() != \"main\" {")
            .unwrap_or_else(|| panic!("{name} does not check its caller"));
        let refusal = body[guard..].find("return Err(").expect("refuses");
        assert!(refusal < 80, "{name}: the refusal must follow the check");
        let first_if = body.find("if ").unwrap();
        assert_eq!(first_if, guard, "{name}: the caller check must come first");
    }
}

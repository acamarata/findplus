//! Build script: single source of truth for the app version.
//!
//! Purpose    : Read the version from cli/pyproject.toml, expose it to the Rust
//!              code as FINDPLUS_VERSION, and write its semver form into
//!              tauri.conf.json so the bundle is named Find+_<ver>_<arch>.dmg
//!              instead of the placeholder 0.0.0 (specs/desktop-app.md).
//! Inputs     : ../../cli/pyproject.toml (`version = "X.Y.Z[.devN]"`).
//! Outputs    : cargo:rustc-env=FINDPLUS_VERSION; tauri.conf.json "version".
//! Constraints: Deterministic — the file is rewritten only when the string
//!              actually differs, so repeated builds do not loop. Tauri parses
//!              the config version as semver, so PEP 440 ".devN" / ".rcN"
//!              suffixes become "-devN" / "-rcN" pre-release tags.

use std::fs;

const FALLBACK: &str = "1.0.0.dev0";

/// `1.0.0.dev0` -> `1.0.0-dev0`; `1.0.0` -> `1.0.0`.
fn to_semver(pep440: &str) -> String {
    let mut parts = pep440.splitn(4, '.');
    let major = parts.next().unwrap_or("0");
    let minor = parts.next().unwrap_or("0");
    let patch = parts.next().unwrap_or("0");
    match parts.next() {
        Some(pre) if !pre.is_empty() => format!("{major}.{minor}.{patch}-{pre}"),
        _ => format!("{major}.{minor}.{patch}"),
    }
}

fn read_pyproject_version() -> String {
    let toml = fs::read_to_string("../../cli/pyproject.toml").unwrap_or_default();
    toml.lines()
        .find(|l| l.starts_with("version"))
        .and_then(|l| l.split('"').nth(1))
        .unwrap_or(FALLBACK)
        .to_string()
}

/// Replace the `"version": "…"` line in tauri.conf.json, writing only on a
/// real change so cargo's rerun-if-changed on that file cannot loop.
fn sync_config_version(semver: &str) {
    let path = "tauri.conf.json";
    let Ok(current) = fs::read_to_string(path) else {
        return;
    };
    let wanted = format!("  \"version\": \"{semver}\",");
    let updated: String = current
        .lines()
        .map(|l| {
            if l.trim_start().starts_with("\"version\":") {
                wanted.as_str()
            } else {
                l
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    if updated != current {
        let _ = fs::write(path, updated);
    }
}

fn main() {
    let version = read_pyproject_version();
    println!("cargo:rerun-if-changed=../../cli/pyproject.toml");
    println!("cargo:rustc-env=FINDPLUS_VERSION={version}");
    sync_config_version(&to_semver(&version));
    tauri_build::build();
}

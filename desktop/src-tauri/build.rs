//! Build script: bakes the daemon/app version into the binary via
//! FINDPLUS_VERSION, read from cli/pyproject.toml so it never has to be
//! hand-maintained in two places. Does NOT rewrite tauri.conf.json's
//! "version" field, which stays a static "0.0.0" as committed.

fn main() {
    let toml = std::fs::read_to_string("../../cli/pyproject.toml").unwrap_or_default();
    if let Some(ver) = toml.lines().find(|l| l.starts_with("version")) {
        let v = ver.split('"').nth(1).unwrap_or("1.0.0.dev0");
        println!("cargo:rustc-env=FINDPLUS_VERSION={v}");
    } else {
        println!("cargo:rustc-env=FINDPLUS_VERSION=1.0.0.dev0");
    }
    tauri_build::build();
}

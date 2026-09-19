// Entry shim. The `[lib] name = "findplus_lib"` target in Cargo.toml holds
// the real tauri::Builder chain (lib.rs); this binary only calls into it.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    findplus_lib::run();
}

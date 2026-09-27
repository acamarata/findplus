//! Loads the tray's "F+" glyph template PNGs from the app bundle (or the
//! source tree in dev), split out of tray.rs to keep that file under the
//! 300-line cap (PRI hard rule 7).
//!
//! Purpose    : Map a `DotState` onto one of the two committed icon files
//!              and read it off disk into an in-memory `tauri::image::Image`.
//! Inputs     : desktop/src-tauri/icons/tray-fplus{,-dim}.png (packaging.py
//!              generates these; see gen-tray-icons.py).
//! Outputs    : A `tauri::image::Image` the tray can pass to `set_icon`.
//! Constraints: Never panics on a missing file -- a corrupt or absent icon
//!              falls back to a transparent 1x1 pixel rather than crashing
//!              the whole menu-bar app.

use tauri::{AppHandle, Manager};

use crate::status::{self, DotState};

/// The "F+" glyph template PNG for this status: full opacity while healthy
/// (Ok), the same glyph at ~38% alpha for everything else, including the
/// very first paint before any status has arrived (initial_status() is Down).
pub fn load_icon(app: &AppHandle, state: &DotState) -> tauri::image::Image<'static> {
    let name = match status::tray_icon_state(state) {
        status::TrayIconState::Normal => "tray-fplus.png",
        status::TrayIconState::Greyed => "tray-fplus-dim.png",
    };
    load_icon_named(app, name)
}

fn load_icon_named(app: &AppHandle, name: &str) -> tauri::image::Image<'static> {
    let candidates = [
        app.path()
            .resource_dir()
            .ok()
            .map(|d| d.join("icons").join(name)),
        Some(
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("icons")
                .join(name),
        ),
    ];
    for candidate in candidates.into_iter().flatten() {
        if let Ok(img) = tauri::image::Image::from_path(&candidate) {
            return img.to_owned();
        }
    }
    // Fallback: a 1x1 transparent pixel if the named PNG cannot be loaded.
    tauri::image::Image::new_owned(vec![0, 0, 0, 0], 1, 1)
}

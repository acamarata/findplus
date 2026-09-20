//! Tauri application builder.
//!
//! Purpose    : Wire the single-instance, notification, shell and dialog
//!              plugins, start the daemon supervisor, status poller, native
//!              alert poller and tray on setup, and route findplus:// opens.
//! Constraints: Cargo.toml declares `[lib] name = "findplus_lib"`, so the
//!              whole tauri::Builder chain lives here; main.rs stays the
//!              two-line `findplus_lib::run()` shim.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|_app, _argv, _cwd| {}))
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            notify::request_notification_permission
        ])
        .setup(|app| {
            tray::setup(app)?;
            windows::open_splash(app.handle());
            daemon::start(app.handle().clone());
            status::start(app.handle().clone());
            first_launch::start(app.handle().clone());
            notify::start(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error building Find+")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Opened { urls, .. } = event {
                for url in urls {
                    urlscheme::handle(app_handle, url.as_str());
                }
            }
        });
}

mod daemon;
mod first_launch;
mod notify;
mod status;
mod tray;
mod urlscheme;
mod windows;

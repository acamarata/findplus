//! Tauri application builder.
//!
//! Purpose    : Wire the single-instance, notification, shell and dialog
//!              plugins, start the daemon supervisor, status poller, native
//!              alert poller and tray on setup, route findplus:// opens, and
//!              expose the in-app login commands (main window only):
//!              `open_signin_window`, `close_signin_window`, `webview_ready`.
//! Constraints: Cargo.toml declares `[lib] name = "findplus_lib"`, so the
//!              whole tauri::Builder chain lives here; main.rs stays the
//!              two-line `findplus_lib::run()` shim.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let special = probe_mode() || selftest_case().is_some();
    let mut builder = tauri::Builder::<tauri::Wry>::default();
    if !special {
        builder = builder.plugin(tauri_plugin_single_instance::init(on_second_instance));
    }
    builder
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            notify::request_notification_permission,
            signin_window::open_signin_window,
            signin_close::close_signin_window,
            signin_events::webview_ready
        ])
        .setup(move |app| if special { setup_special(app) } else { on_setup(app) })
        .build(tauri::generate_context!())
        .expect("error building Find+")
        .run(on_run_event);
}

/// True only in a `login-probe` build launched with `--probe-google-embedded`.
fn probe_mode() -> bool {
    #[cfg(feature = "login-probe")]
    return probe_login::requested();
    #[cfg(not(feature = "login-probe"))]
    false
}

/// The sign-in self-test case (debug builds only; tests/signin_e2e.rs).
fn selftest_case() -> Option<String> {
    #[cfg(debug_assertions)]
    return signin_selftest::requested();
    #[cfg(not(debug_assertions))]
    None
}

/// Probe or self-test launch: no tray, daemon or splash, just one window.
fn setup_special(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "macos")]
    app.set_activation_policy(tauri::ActivationPolicy::Regular);
    #[cfg(debug_assertions)]
    if let Some(case) = selftest_case() {
        signin_selftest::start(app.handle(), &case);
        return Ok(());
    }
    #[cfg(feature = "login-probe")]
    probe_login::start(app.handle());
    let _ = app;
    Ok(())
}

/// A second launch from Applications/Spotlight/`open` while Find+ is already
/// running is killed by the single-instance plugin; this callback runs in
/// the FIRST (already-running) instance, so re-opening the app must behave
/// like the tray's left click, not do nothing as it did through v1.1.3 (the
/// callback was a no-op).
fn on_second_instance(app: &tauri::AppHandle, _argv: Vec<String>, _cwd: String) {
    windows::open_main(app);
}

fn on_setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    // Info.plist's LSUIElement keeps Find+ out of the Dock at launch, but
    // Tauri's own default (NSApplicationActivationPolicyRegular) would
    // re-show it the moment the event loop starts, so Accessory must be set
    // here explicitly -- this is a permanent menu-bar-only app, never a Dock
    // icon that appears while a window is open.
    #[cfg(target_os = "macos")]
    app.set_activation_policy(tauri::ActivationPolicy::Accessory);
    tray::setup(app)?;
    windows::open_splash(app.handle());
    daemon::start(app.handle().clone());
    status::start(app.handle().clone());
    first_launch::start(app.handle().clone());
    notify::start(app.handle().clone());
    Ok(())
}

fn on_run_event(app_handle: &tauri::AppHandle, event: tauri::RunEvent) {
    match event {
        tauri::RunEvent::Opened { urls, .. } => {
            for url in urls {
                urlscheme::handle(app_handle, url.as_str());
            }
        }
        // Fires when the Dock/Spotlight/Finder reactivates an already-running
        // app that has no Dock icon of its own to click. Bring the dashboard
        // forward exactly like the tray's left click.
        #[cfg(target_os = "macos")]
        tauri::RunEvent::Reopen { .. } => windows::open_main(app_handle),
        // A menu-bar app must outlive its windows. Without this, closing the
        // splash with setup already finished (or closing the dashboard) left
        // no window, Tauri quit with code 0 and the tray icon vanished while
        // the sidecar kept running (v1.1.0). `code` is None only for that
        // implicit last-window exit; the tray's Quit path exits the process
        // itself.
        tauri::RunEvent::ExitRequested { code: None, api, .. } => api.prevent_exit(),
        _ => {}
    }
}

mod attention;
mod daemon;
mod first_launch;
mod notify;
#[cfg(all(debug_assertions, feature = "login-probe"))]
mod probe_fake;
#[cfg(feature = "login-probe")]
mod probe_login;
#[cfg(any(feature = "login-probe", test))]
mod probe_logic;
mod signin_close;
mod signin_events;
#[cfg(debug_assertions)]
mod signin_fake;
mod signin_hosts;
mod signin_http;
mod signin_logic;
mod signin_page;
mod signin_machine;
mod signin_script;
#[cfg(debug_assertions)]
mod signin_selftest;
mod signin_session;
mod signin_start;
mod signin_window;
mod status;
mod tray;
mod urlscheme;
mod windows;

//! In-app sign-in: the controlled Google sign-in window.
//!
//! Purpose    : Open a window Find+ controls on Google's sign-in page with a
//!              throwaway cookie store, watch it (signin_session.rs), and tell
//!              the dashboard what happened through `signin-progress` and
//!              `signin-result` events. Spec: .github/docs/specs/in-app-login.md.
//! Inputs     : `open_signin_window` from the main window only, the tray's
//!              attention item, or a gated deep link.
//! Outputs    : The `signin-google` window, events to `main`, daemon calls.
//! Constraints: Incognito (non-persistent WKWebsiteDataStore); no capability
//!              names this label, so Google's page cannot call any Tauri
//!              command; navigation is allow-listed (signin_logic.rs) and
//!              127.0.0.1 is refused; popups and downloads are refused; the
//!              store is wiped and the window destroyed on every exit path.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Sender};
use tauri::webview::{DownloadEvent, NewWindowResponse, PageLoadEvent};
use tauri::{
    AppHandle, Emitter, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent,
};

use serde_json::json;

use crate::attention::{Need, Provider};
use crate::signin_http::SESSION_COOKIE;
use crate::signin_logic::{self as logic, Bridge, CookieFacts, Hosts, Nav};
use crate::signin_machine::Mode;
use crate::signin_script::{self as script, ScriptOrigins};

pub const LABEL: &str = "signin-google";
static ACTIVE: AtomicBool = AtomicBool::new(false);
/// Set by the debug self-test: no dashboard to focus afterwards.
pub static SELFTEST: AtomicBool = AtomicBool::new(false);

/// What the window reports to its session thread. Never carries a cookie.
#[derive(Debug)]
pub enum Msg {
    Bridge(Bridge),
    Loaded(String),
    Title(String),
    /// A refused navigation off Google (host logged, not sent).
    Outside,
    Closed,
}

/// Open the dashboard's Google sign-in from the main window. Apple has no web
/// sign-in (spec §5), so it asks the dashboard to open its Apple sheet instead.
#[tauri::command]
pub fn open_signin_window(
    app: AppHandle,
    webview: tauri::Webview,
    provider: String,
    mode: Option<String>,
    begin: Option<serde_json::Value>,
) -> Result<String, String> {
    if webview.label() != "main" {
        return Err("not_main_window".into());
    }
    match provider.as_str() {
        "google" => {
            let mode = Mode::parse(mode.as_deref()).ok_or("bad_mode")?;
            Ok(open(&app, mode, begin).to_string())
        }
        "apple" => {
            open_apple_sheet(&app);
            Ok("apple_sheet".into())
        }
        _ => Err("unsupported_provider".into()),
    }
}

/// Open (or focus) the Google sign-in window. Returns "opened" or "already_open".
/// `begin` is the card's own begin reply (contract §2), or None to mint one here.
pub fn open(app: &AppHandle, mode: Mode, begin: Option<serde_json::Value>) -> &'static str {
    if let Some(win) = app.get_webview_window(LABEL) {
        let _ = win.show();
        let _ = win.set_focus();
        return "already_open";
    }
    if ACTIVE.swap(true, Ordering::SeqCst) {
        return "already_open";
    }
    let app = app.clone();
    std::thread::spawn(move || {
        crate::signin_start::run(&app, mode, begin);
        ACTIVE.store(false, Ordering::SeqCst);
        crate::attention::refresh_soon(&app);
    });
    "opened"
}

/// Open the login a provider needs (tray item, gated deep link).
pub fn open_for(app: &AppHandle, provider: Provider, need: Need) {
    match (provider, need) {
        (Provider::Google, Need::Signin) => drop(open(app, Mode::Signin, None)),
        (Provider::Google, Need::Unlock) => drop(open(app, Mode::Unlock, None)),
        (Provider::Apple, _) => open_apple_sheet(app),
    }
}

/// Apple signs in through the dashboard's own sheet: show Settings and ask
/// the page to open it.
pub fn open_apple_sheet(app: &AppHandle) {
    crate::windows::open_settings(app);
    let _ = app.emit_to("main", "signin-apple-sheet", ());
}

/// Send one event to the dashboard window. (`listen_any` in the debug
/// self-test sees it too.)
pub fn emit(app: &AppHandle, event: &str, payload: serde_json::Value) {
    let _ = app.emit_to("main", event, payload);
}

/// Focus returns to the dashboard once the window is gone.
pub fn focus_main(app: &AppHandle) {
    if !SELFTEST.load(Ordering::SeqCst) {
        crate::windows::open_main(app);
    }
}

/// The debug-only fake server origin, from FINDPLUS_SIGNIN_TEST_BASE. A
/// release build has no way to point the window anywhere but Google.
pub fn hosts() -> Hosts {
    #[cfg(debug_assertions)]
    if let Ok(base) = std::env::var("FINDPLUS_SIGNIN_TEST_BASE") {
        let origin = logic::origin_of(&base);
        if origin.starts_with("http://127.0.0.1:") {
            return Hosts {
                test_origin: Some(origin),
            };
        }
    }
    Hosts::default()
}

/// The first page for this mode.
pub fn start_url(mode: Mode, hosts: &Hosts) -> String {
    match (&hosts.test_origin, mode) {
        (Some(t), Mode::Signin) => format!("{t}/EmbeddedSetup"),
        (Some(t), Mode::Unlock) => format!("{t}/"),
        (None, Mode::Signin) => logic::GOOGLE_SIGNIN_START.to_string(),
        (None, Mode::Unlock) => logic::GOOGLE_UNLOCK_START.to_string(),
    }
}

fn init_script(hosts: &Hosts) -> String {
    match &hosts.test_origin {
        Some(t) => script::init_script(&ScriptOrigins {
            unlock: t,
            account: t,
            account_path: "/myaccount",
        }),
        None => script::init_script(&script::GOOGLE_ORIGINS),
    }
}

/// Build the window. Every callback only forwards a `Msg`; decisions happen
/// on the session thread, except the allow-list, which must answer inline.
pub fn build(
    app: &AppHandle,
    mode: Mode,
    hosts: &Hosts,
    tx: Sender<Msg>,
) -> Result<WebviewWindow, String> {
    let url: tauri::Url = start_url(mode, hosts)
        .parse()
        .map_err(|_| "bad start URL".to_string())?;
    let (nav_tx, load_tx, title_tx) = (tx.clone(), tx.clone(), tx.clone());
    let nav_hosts = hosts.clone();
    let title = logic::window_title("Google", url.host_str().unwrap_or(""));
    let win = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::External(url))
        .title(title)
        .inner_size(480.0, 720.0)
        .incognito(true)
        .focused(true)
        .initialization_script(init_script(hosts))
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .on_download(|_, e| !matches!(e, DownloadEvent::Requested { .. }))
        .on_navigation(move |u| on_navigation(u, &nav_hosts, &nav_tx))
        .on_page_load(move |w, p| on_page_load(&w, p.url(), p.event(), &load_tx))
        .on_document_title_changed(move |_, t| {
            let _ = title_tx.send(Msg::Title(t));
        })
        .build()
        .map_err(|e| e.to_string())?;
    win.on_window_event(move |ev| match ev {
        WindowEvent::CloseRequested { api, .. } => {
            api.prevent_close();
            let _ = tx.send(Msg::Closed);
        }
        WindowEvent::Destroyed => {
            let _ = tx.send(Msg::Closed);
        }
        _ => {}
    });
    Ok(win)
}

fn on_navigation(url: &tauri::Url, hosts: &Hosts, tx: &Sender<Msg>) -> bool {
    let host = url.host_str().unwrap_or("");
    match logic::decide_navigation(url.as_str(), url.scheme(), host, hosts) {
        Nav::Allow => true,
        Nav::Bridge(b) => {
            let _ = tx.send(Msg::Bridge(b));
            false
        }
        Nav::Outside(h) => {
            log::info!("signin: the page tried to leave Google for host {h}");
            let _ = tx.send(Msg::Outside);
            false
        }
        Nav::Block(h) => {
            log::info!("signin: refused a navigation to host {h}");
            false
        }
    }
}

fn on_page_load(win: &WebviewWindow, url: &tauri::Url, ev: PageLoadEvent, tx: &Sender<Msg>) {
    if ev != PageLoadEvent::Finished {
        return;
    }
    let _ = win.set_title(&logic::window_title("Google", url.host_str().unwrap_or("")));
    log::debug!("signin: loaded {}", logic::redact_url(url.as_str()));
    let _ = tx.send(Msg::Loaded(url.to_string()));
}

/// A fresh channel for one session.
pub fn channel() -> (Sender<Msg>, mpsc::Receiver<Msg>) {
    mpsc::channel()
}

/// Tell the dashboard card which phase the window is in.
pub fn progress(app: &AppHandle, mode: Mode, phase: &str, stuck: bool) {
    let payload =
        json!({ "provider": "google", "mode": mode.wire(), "phase": phase, "stuck": stuck });
    emit(app, "signin-progress", payload);
}

/// The window never opened (daemon refused, or the window failed to build).
pub fn fail_early(app: &AppHandle, mode: Mode, message: &str) {
    let payload = json!({ "provider": "google", "mode": mode.wire(), "outcome": "error", "message": message });
    emit(app, "signin-result", payload);
}

/// The dashboard's PIN session, read from the main window's own store, so a
/// dashboard unlocked behind a PIN can start a sign-in. None without a PIN.
pub fn session_cookie(app: &AppHandle, base: &str) -> Option<String> {
    let main = app.get_webview_window("main")?;
    let cookies = main.cookies_for_url(base.parse().ok()?).ok()?;
    let c = cookies.iter().find(|c| c.name() == SESSION_COOKIE)?;
    Some(format!("{SESSION_COOKIE}={}", c.value()))
}

/// Every cookie in the window's store, reduced to what the picker needs.
/// wry's macOS `cookies_for_url` keeps only exact-host matches, so the
/// session reads them all and signin_page.rs does the matching. Call from a
/// worker thread (blocks up to 1 s on macOS; deadlocks on Windows from a
/// handler).
pub fn cookie_facts(win: &WebviewWindow) -> Vec<CookieFacts> {
    let cookies = win.cookies().unwrap_or_default();
    cookies
        .iter()
        .map(|c| CookieFacts {
            name: c.name().to_string(),
            value: c.value().to_string(),
            domain: c.domain().unwrap_or("").to_string(),
            expires: c.expires_datetime().map(|t| t.unix_timestamp()),
        })
        .collect()
}

/// Unix seconds now (0 if the clock is before 1970).
pub fn now_secs() -> i64 {
    let since = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH);
    since.map(|d| d.as_secs() as i64).unwrap_or(0)
}

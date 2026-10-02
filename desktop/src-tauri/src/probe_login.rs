//! Package 0 gate probe: the window, the poller and the results dialog.
//!
//! Purpose    : Let the owner test, with a real Google account, whether
//!              https://accounts.google.com/EmbeddedSetup works in a macOS
//!              webview and whether an `oauth_token` cookie becomes readable.
//! Constraints: Built only with the `login-probe` cargo feature, started only
//!              with `--probe-google-embedded`. The window is incognito, has
//!              no capability (no IPC commands), may only navigate to Google
//!              sign-in hosts, and its store is wiped on close. The cookie
//!              value is never stored, logged, printed or sent: only its
//!              length leaves `read_cookies`.
use crate::probe_logic::{self as logic, CookieInfo, ProbeFacts};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};

const GOOGLE_START: &str = "https://accounts.google.com/EmbeddedSetup";
const LABEL: &str = "probe-google";
const TIMEOUT: Duration = Duration::from_secs(600);
const CHECK_JS: &str = r#"JSON.stringify({ua:navigator.userAgent,rej:/may not be secure|disallowed_useragent|couldn.t sign you in/i.test((document.body&&document.body.innerText)||"")})"#;

/// True when the app was launched with `--probe-google-embedded`.
pub fn requested() -> bool {
    std::env::args().any(|a| a == "--probe-google-embedded")
}

#[derive(Default)]
struct Seen {
    trail: Vec<String>,
    url: String,
    title: String,
    blocked: Vec<String>,
}

type Shared = Arc<Mutex<Seen>>;

/// Open the probe window and start watching it.
pub fn start(app: &AppHandle) {
    let (start_url, fake) = start_url();
    let seen: Shared = Arc::default();
    let win = match build_window(app, &start_url, fake, seen.clone()) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("probe: could not open the window: {e}");
            app.exit(1);
            return;
        }
    };
    let (done, started) = (Arc::new(AtomicBool::new(false)), Instant::now());
    let ctx = Ctx { app: app.clone(), win: win.clone(), seen, done, started, fake };
    let c = ctx.clone();
    win.on_window_event(move |ev| {
        if let WindowEvent::CloseRequested { api, .. } = ev {
            api.prevent_close();
            finish_async(c.clone());
        }
    });
    std::thread::spawn(move || poll(ctx));
}

fn start_url() -> (String, bool) {
    #[cfg(debug_assertions)]
    if let Some(u) = crate::probe_fake::start_from_env() {
        return (u, true);
    }
    (GOOGLE_START.to_string(), false)
}

fn build_window(app: &AppHandle, url: &str, fake: bool, seen: Shared) -> tauri::Result<WebviewWindow> {
    let (nav_seen, title_seen) = (seen.clone(), seen);
    WebviewWindowBuilder::new(app, LABEL, WebviewUrl::External(url.parse().expect("start url")))
        .title("Find+ sign-in probe (test window)")
        .inner_size(520.0, 760.0)
        .incognito(true)
        .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
        .on_navigation(move |u| on_navigation(&nav_seen, u, fake))
        .on_document_title_changed(move |_, t| title_seen.lock().unwrap().title = t)
        .build()
}

fn on_navigation(seen: &Shared, url: &tauri::Url, fake: bool) -> bool {
    let host = url.host_str().unwrap_or("");
    let ok = logic::allow_navigation(url.scheme(), host, fake);
    let mut s = seen.lock().unwrap();
    if ok {
        s.url = url.to_string();
        logic::push_trail(&mut s.trail, logic::redact(url.as_str()));
    } else if !s.blocked.contains(&host.to_string()) {
        s.blocked.push(host.to_string());
    }
    ok
}

#[derive(Clone)]
struct Ctx {
    app: AppHandle,
    win: WebviewWindow,
    seen: Shared,
    done: Arc<AtomicBool>,
    started: Instant,
    fake: bool,
}

/// Watch for the cookie; finish 3 seconds after it first appears, or at timeout.
fn poll(ctx: Ctx) {
    let mut first_seen: Option<Instant> = None;
    while !ctx.done.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_secs(1));
        if logic::find_oauth_token(&read_cookies(&ctx.win)).is_some() {
            first_seen.get_or_insert_with(Instant::now);
        }
        let settled = first_seen.is_some_and(|t| t.elapsed() > Duration::from_secs(3));
        let unattended = ctx.fake
            && std::env::var_os("FINDPLUS_PROBE_NO_DIALOG").is_some()
            && ctx.started.elapsed() > Duration::from_secs(4);
        if settled || unattended || ctx.started.elapsed() > TIMEOUT {
            finish_async(ctx.clone());
            return;
        }
    }
}

/// Cookies reduced to name, domain and value length. The value is dropped here.
fn read_cookies(win: &WebviewWindow) -> Vec<CookieInfo> {
    win.cookies()
        .unwrap_or_default()
        .iter()
        .map(|c| CookieInfo {
            name: c.name().to_string(),
            domain: c.domain().unwrap_or("").to_string(),
            value_len: c.value().len(),
        })
        .collect()
}

fn finish_async(ctx: Ctx) {
    if ctx.done.swap(true, Ordering::SeqCst) {
        return;
    }
    std::thread::spawn(move || finish(ctx));
}

/// Ask the page for its user agent and whether its text is a rejection.
fn ask_page(win: &WebviewWindow) -> (String, Option<bool>) {
    let (tx, rx) = mpsc::channel::<String>();
    let sent = win.eval_with_callback(CHECK_JS, move |r| {
        let _ = tx.send(r);
    });
    let raw = sent.ok().and_then(|_| rx.recv_timeout(Duration::from_secs(3)).ok());
    let parsed = raw
        .and_then(|r| serde_json::from_str::<String>(&r).ok())
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok());
    match parsed {
        Some(v) => (
            v["ua"].as_str().unwrap_or("unavailable").to_string(),
            v["rej"].as_bool(),
        ),
        None => ("unavailable (page did not answer)".to_string(), None),
    }
}

fn finish(ctx: Ctx) {
    let cookies = read_cookies(&ctx.win);
    let (user_agent, page_text_rejected) = ask_page(&ctx.win);
    let facts = {
        let s = ctx.seen.lock().unwrap();
        let live = ctx.win.url().map(|u| u.to_string()).unwrap_or_default();
        ProbeFacts {
            trail: s.trail.clone(),
            final_url: if live.is_empty() { s.url.clone() } else { live },
            final_title: s.title.clone(),
            page_text_rejected,
            blocked_hosts: s.blocked.clone(),
            cookie_len: logic::find_oauth_token(&cookies),
            user_agent,
            seconds: ctx.started.elapsed().as_secs(),
            fake_server: ctx.fake,
        }
    };
    let _ = ctx.win.clear_all_browsing_data();
    let _ = ctx.win.destroy();
    let report = logic::report_text(&facts);
    println!("{report}");
    if !(ctx.fake && std::env::var_os("FINDPLUS_PROBE_NO_DIALOG").is_some()) {
        show_results(&ctx.app, &report);
    }
    ctx.app.exit(0);
}

/// Native dialog with a copy button. Loops until the owner picks Close.
fn show_results(app: &AppHandle, report: &str) {
    let mut note = "";
    loop {
        let copy = app
            .dialog()
            .message(format!("{note}{report}"))
            .title("Find+ probe result")
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Copy report".into(),
                "Close".into(),
            ))
            .blocking_show();
        if !copy {
            return;
        }
        note = if copy_to_clipboard(report) {
            "(Copied to the clipboard.)\n\n"
        } else {
            "(Could not copy; select the text from the terminal instead.)\n\n"
        };
    }
}

fn copy_to_clipboard(text: &str) -> bool {
    use std::io::Write;
    use std::process::{Command, Stdio};
    let child = Command::new("pbcopy").stdin(Stdio::piped()).spawn();
    match child {
        Ok(mut c) => {
            let wrote = c.stdin.take().is_some_and(|mut i| i.write_all(text.as_bytes()).is_ok());
            wrote && c.wait().is_ok_and(|s| s.success())
        }
        Err(_) => false,
    }
}

//! In-app sign-in: one session's worker thread.
//!
//! Purpose    : Mint the daemon state, open the window, then loop: read the
//!              window's messages and its cookies every 500 ms, feed the state
//!              machine (signin_machine.rs) and run its effects. Ends by wiping
//!              the store, destroying the window, telling the daemon and the
//!              dashboard, and focusing the dashboard.
//! Inputs     : `Msg` from signin_window.rs callbacks; the cookie store.
//! Outputs    : `signin-progress` / `signin-result` events; daemon calls.
//! Constraints: Runs on its own thread (never the main thread: `cookies()`
//!              blocks, and deadlocks on Windows from an event handler). The
//!              token and the vault keys live in `Option`s that are `take()`n
//!              into exactly one POST; nothing here logs or emits them.

use std::sync::mpsc::{Receiver, RecvTimeoutError};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, WebviewWindow};

use crate::signin_http::{Begin, Daemon};
use crate::signin_logic::{self as logic, Bridge, CookieFacts, Hosts};
use crate::signin_machine::{result_payload, step, Effect, Input, Mode, Outcome, Phase};
use crate::signin_window::{self as window, Msg};

const TICK: Duration = Duration::from_millis(500);
const TIMEOUT: Duration = Duration::from_secs(600);
const STUCK_AFTER: Duration = Duration::from_secs(180);
/// Unlock-only mode: how long the account page gets to report its address.
const ACCOUNT_WAIT: Duration = Duration::from_secs(6);

struct Session {
    app: AppHandle,
    win: WebviewWindow,
    mode: Mode,
    phase: Phase,
    daemon: Daemon,
    begin: Begin,
    hosts: Hosts,
    token: Option<String>,
    vault: Option<String>,
    account: Option<String>,
    message: Option<String>,
    reason: Option<&'static str>,
    title: String,
    started: Instant,
    last_activity: Instant,
    home_seen: Option<Instant>,
    stuck_sent: bool,
}

/// Run one sign-in session to its end. Never panics on a daemon or window error.
pub fn run(app: &AppHandle, mode: Mode) {
    window::progress(app, mode, "starting", false);
    let base = crate::daemon::daemon_base();
    let daemon = Daemon {
        cookie: window::session_cookie(app, &base),
        base,
    };
    let begin = match daemon.begin(mode.wire()) {
        Ok(b) => b,
        Err(message) => return window::fail_early(app, mode, &message),
    };
    let hosts = window::hosts();
    let (tx, rx) = window::channel();
    let win = match window::build(app, mode, &hosts, tx) {
        Ok(w) => w,
        Err(e) => {
            log::warn!("signin: could not open the window: {e}");
            daemon.event(&begin.state, "failed", Some("window"));
            return window::fail_early(app, mode, "Find+ could not open the sign-in window.");
        }
    };
    daemon.event(&begin.state, "opened", None);
    let now = Instant::now();
    let mut s = Session {
        app: app.clone(),
        win,
        mode,
        phase: Phase::Waiting,
        daemon,
        begin,
        hosts,
        token: None,
        vault: None,
        account: None,
        message: None,
        reason: None,
        title: String::new(),
        started: now,
        last_activity: now,
        home_seen: None,
        stuck_sent: false,
    };
    window::progress(app, mode, "waiting", false);
    s.daemon.event(&s.begin.state, "waiting", None);
    s.run_loop(&rx);
}

fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

impl Session {
    fn run_loop(&mut self, rx: &Receiver<Msg>) {
        while self.phase != Phase::Done {
            match rx.recv_timeout(TICK) {
                Ok(msg) => self.on_msg(msg),
                Err(RecvTimeoutError::Timeout) => self.on_tick(),
                Err(RecvTimeoutError::Disconnected) => self.feed(Input::UserClosed),
            }
        }
    }

    fn on_msg(&mut self, msg: Msg) {
        match msg {
            Msg::Closed | Msg::Bridge(Bridge::Cancel) => self.feed(Input::UserClosed),
            Msg::Bridge(Bridge::Vault(keys)) => {
                self.vault = Some(keys);
                self.feed(Input::VaultKeys);
            }
            Msg::Bridge(Bridge::Close) => self.feed(Input::BridgeClose),
            Msg::Bridge(Bridge::Account(a)) => {
                self.account = Some(a);
                self.feed(Input::AccountKnown);
            }
            Msg::Bridge(Bridge::NoAccount) => self.feed(Input::AccountKnown),
            Msg::Bridge(Bridge::Bad) => log::info!("signin: ignored a malformed bridge message"),
            Msg::Loaded(url) => self.on_loaded(&url),
            Msg::Outside => {
                self.reason = Some("outside_google");
                self.feed(Input::Blocked);
            }
            Msg::Title(t) => {
                self.last_activity = Instant::now();
                let signal = logic::blocked_signal("", &t);
                self.title = t;
                if signal.is_some() {
                    self.reason = signal;
                    self.feed(Input::Blocked);
                }
            }
        }
    }

    fn on_loaded(&mut self, url: &str) {
        self.last_activity = Instant::now();
        if logic::is_account_home(url, &self.hosts) {
            self.home_seen.get_or_insert_with(Instant::now);
        }
        let signal = logic::blocked_signal(url, &self.title);
        if signal.is_some() {
            self.reason = signal;
        }
        self.feed(Input::PageLoaded {
            blocked: signal.is_some(),
        });
    }

    fn on_tick(&mut self) {
        if self.started.elapsed() > TIMEOUT {
            return self.feed(Input::TimedOut);
        }
        let waiting = self.phase == Phase::Waiting;
        if waiting && !self.stuck_sent && self.last_activity.elapsed() > STUCK_AFTER {
            self.stuck_sent = true;
            window::progress(&self.app, self.mode, "waiting", true);
        }
        if waiting
            && self.mode == Mode::Unlock
            && self.home_seen.is_some_and(|t| t.elapsed() > ACCOUNT_WAIT)
        {
            return self.feed(Input::AccountKnown);
        }
        if waiting && self.mode == Mode::Signin {
            if let Some(token) = self.read_token() {
                self.token = Some(token);
                self.feed(Input::CookieFound);
            }
        }
    }

    /// Read every cookie (wry's macOS `cookies_for_url` only keeps exact-host
    /// matches) and let the pure picker choose. The value stays in memory.
    fn read_token(&self) -> Option<String> {
        let facts: Vec<CookieFacts> = self
            .win
            .cookies()
            .unwrap_or_default()
            .iter()
            .map(|c| CookieFacts {
                name: c.name().to_string(),
                value: c.value().to_string(),
                domain: c.domain().unwrap_or("").to_string(),
                expires: c.expires_datetime().map(|t| t.unix_timestamp()),
            })
            .collect();
        logic::pick_oauth_token(&facts, now_secs(), &self.hosts)
    }

    /// Step the machine and run effects until it settles.
    fn feed(&mut self, first: Input) {
        let mut next = Some(first);
        while let Some(input) = next.take() {
            let (phase, effect) = step(self.phase, self.mode, &input);
            if phase != self.phase && phase != Phase::Done {
                window::progress(&self.app, self.mode, phase.wire(), false);
            }
            self.phase = phase;
            next = self.run_effect(effect);
        }
    }

    fn run_effect(&mut self, effect: Effect) -> Option<Input> {
        match effect {
            Effect::None => None,
            Effect::PostToken => Some(self.post_token()),
            Effect::NavigateUnlock => self.navigate_unlock(),
            Effect::PostUnlock => Some(self.post_unlock()),
            Effect::Finish(outcome) => {
                self.finish(outcome);
                None
            }
        }
    }

    fn post_token(&mut self) -> Input {
        let token = self.token.take().unwrap_or_default();
        match self.daemon.token(&self.begin.state, token) {
            Ok(reply) => {
                self.account = reply.account;
                let has_unlock_url = self.begin.unlock_url.is_some();
                Input::TokenAccepted {
                    needs_unlock: reply.needs_unlock,
                    has_unlock_url,
                }
            }
            Err(message) => {
                self.message = Some(message);
                Input::TokenRejected
            }
        }
    }

    fn navigate_unlock(&mut self) -> Option<Input> {
        let url = self
            .begin
            .unlock_url
            .as_deref()
            .and_then(|u| u.parse().ok());
        match url.map(|u| self.win.navigate(u)) {
            Some(Ok(())) => None,
            _ => {
                self.message = Some("Find+ could not open the unlock page.".into());
                Some(Input::Failed)
            }
        }
    }

    fn post_unlock(&mut self) -> Input {
        let keys = self.vault.take().unwrap_or_default();
        match self
            .daemon
            .unlock(&self.begin.state, keys, self.account.as_deref())
        {
            Ok(()) => Input::UnlockStored,
            Err(message) => {
                self.message = Some(message);
                Input::UnlockRejected
            }
        }
    }

    /// Every exit path: wipe, destroy, tell the daemon and the dashboard.
    fn finish(&mut self, outcome: Outcome) {
        self.token = None;
        self.vault = None;
        let _ = self.win.clear_all_browsing_data();
        let _ = self.win.destroy();
        let (event, reason) = outcome.daemon_event(self.reason);
        self.daemon.event(&self.begin.state, event, reason);
        let payload = result_payload(
            self.mode,
            outcome,
            self.account.as_deref(),
            self.message.as_deref(),
            self.reason,
        );
        log::info!("signin: finished, outcome {}", outcome.wire());
        window::emit(&self.app, "signin-result", payload);
        window::focus_main(&self.app);
    }
}

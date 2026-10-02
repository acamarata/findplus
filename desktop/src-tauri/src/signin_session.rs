//! In-app sign-in: one session's worker thread.
//!
//! Purpose    : Loop over one open window (signin_start.rs opens it): read the
//!              window's messages and its cookies every 500 ms, feed the state
//!              machine (signin_machine.rs) and run its effects. Ends by wiping
//!              the store, destroying the window, telling the daemon and the
//!              dashboard, and focusing the dashboard.
//! Inputs     : `Msg` from signin_window.rs callbacks; the cookie store.
//! Outputs    : `signin-progress` / `signin-result` events; daemon calls.
//!              The daemon calls and the outside close check live in
//!              signin_session_calls.rs (a child module, same fields).
//! Constraints: Runs on its own thread (never the main thread: `cookies()`
//!              blocks, and deadlocks on Windows from an event handler). The
//!              token and the vault keys live in `Option`s that are `take()`n
//!              into exactly one POST; nothing here logs or emits them.

use std::sync::mpsc::{Receiver, RecvTimeoutError};
use std::time::{Duration, Instant};
use tauri::{AppHandle, WebviewWindow};

use crate::signin_hosts::FrameWatch;
use crate::signin_http::{Begin, Daemon};
use crate::signin_logic::{self as logic, Bridge, Hosts};
use crate::signin_machine::{
    is_exchanging, restarts_budget, result_payload, step, Effect, Input, Mode, Outcome, Phase,
    ACCOUNT_UNKNOWN, MSG_ACCOUNT_UNKNOWN,
};
use crate::signin_window::{self as window, Msg};

const TICK: Duration = Duration::from_millis(500);
const TIMEOUT: Duration = Duration::from_secs(600);
const STUCK_AFTER: Duration = Duration::from_secs(180);
/// Unlock-only mode: how long the account page gets to report its address.
const ACCOUNT_WAIT: Duration = Duration::from_secs(6);

pub struct Session {
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
    /// The address the account page showed (unlock-only mode).
    account_hint: Option<String>,
    message: Option<String>,
    reason: Option<String>,
    title: String,
    started: Instant,
    /// The 10-minute budget starts at open and again at the unlock step.
    budget_from: Instant,
    last_activity: Instant,
    home_seen: Option<Instant>,
    stuck_sent: bool,
    /// Hash of a cookie value the daemon called malformed: never posted twice.
    rejected_token: Option<u64>,
    token_retried: bool,
    /// Ticks since the daemon's progress was last read (signin_close.rs).
    ticks_since_poll: u32,
    /// Main frame or sub-frame, for refused off-Google hosts.
    frames: FrameWatch,
}

impl Session {
    /// A session for a window that is already open.
    pub fn new(
        app: &AppHandle,
        win: WebviewWindow,
        mode: Mode,
        daemon: Daemon,
        begin: Begin,
        hosts: Hosts,
    ) -> Self {
        let now = Instant::now();
        Session {
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
            account_hint: None,
            message: None,
            reason: None,
            title: String::new(),
            started: now,
            budget_from: now,
            last_activity: now,
            home_seen: None,
            stuck_sent: false,
            rejected_token: None,
            token_retried: false,
            ticks_since_poll: 0,
            frames: FrameWatch::default(),
        }
    }
}

impl Session {
    /// Run the window to its end: messages, a 500 ms tick, the machine.
    pub fn run_loop(&mut self, rx: &Receiver<Msg>) {
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
                self.account_hint = Some(a);
                self.feed(Input::AccountKnown);
            }
            Msg::Bridge(Bridge::NoAccount) => self.account_unknown(),
            Msg::Bridge(Bridge::Bad) => log::info!("signin: ignored a malformed bridge message"),
            Msg::Committed => self.frames.committed(),
            Msg::Loaded(url) => {
                self.frames.finished();
                self.on_loaded(&url);
            }
            Msg::Outside(host) => {
                let ms = self.started.elapsed().as_millis() as u64;
                if !self.frames.refused_outside(&host, ms) {
                    log::info!("signin: refused a frame from host {host}");
                }
            }
            Msg::Title(t) => {
                self.last_activity = Instant::now();
                let signal = logic::blocked_signal("", &t);
                self.title = t;
                if let Some(r) = signal {
                    self.reason = Some(r.into());
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
        // The daemon classifies too (contract §3.5); either one may say blocked.
        let (host, path) = logic::host_and_path(url);
        let class = logic::title_class(&self.title);
        let signal = logic::blocked_signal(url, &self.title)
            .map(String::from)
            .or_else(|| self.daemon.classify(&self.begin.state, &host, &path, class));
        let blocked = signal.is_some();
        if blocked {
            self.reason = signal;
        }
        self.feed(Input::PageLoaded { blocked });
    }

    fn on_tick(&mut self) {
        if self.budget_from.elapsed() > TIMEOUT {
            return self.feed(Input::TimedOut);
        }
        let ms = self.started.elapsed().as_millis() as u64;
        if let Some(host) = self.frames.left_google(ms) {
            // Only a top-level move off Google ends the window (r12 #2).
            log::info!("signin: the page tried to leave Google for host {host}");
            self.reason = Some("outside_google".into());
            return self.feed(Input::Blocked);
        }
        if self.stop_asked() {
            return self.feed(Input::UserClosed);
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
            return self.account_unknown();
        }
        if waiting && self.mode == Mode::Signin {
            let fresh = self
                .read_token()
                .filter(|t| Some(logic::fingerprint(t)) != self.rejected_token);
            if let Some(token) = fresh {
                self.token = Some(token);
                self.feed(Input::CookieFound);
            }
        }
    }

    /// Unlock-only mode without an address: stop, say why, offer a retry.
    fn account_unknown(&mut self) {
        if self.mode == Mode::Unlock && self.phase == Phase::Waiting {
            self.reason = Some(ACCOUNT_UNKNOWN.into());
            self.message = Some(MSG_ACCOUNT_UNKNOWN.into());
        }
        self.feed(Input::AccountUnknown);
    }

    /// The live sign-in cookie, if the window's store holds one.
    fn read_token(&self) -> Option<String> {
        logic::pick_oauth_token(
            &window::cookie_facts(&self.win),
            window::now_secs(),
            &self.hosts,
        )
    }

    /// Step the machine and run effects until it settles.
    fn feed(&mut self, first: Input) {
        let mut next = Some(first);
        while let Some(input) = next.take() {
            let (phase, effect) = step(self.phase, self.mode, &input);
            if phase != self.phase && phase != Phase::Done {
                window::progress(&self.app, self.mode, phase.wire(), false);
            }
            if restarts_budget(self.phase, phase) {
                self.budget_from = Instant::now();
            }
            window::set_exchanging(is_exchanging(phase));
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

    /// Every exit path: tell the daemon, wipe, destroy, tell the dashboard.
    fn finish(&mut self, outcome: Outcome) {
        self.token = None;
        self.vault = None;
        let (event, reason) = outcome.daemon_event(self.reason.as_deref());
        self.daemon.event(&self.begin.state, event, reason);
        let _ = self.win.clear_all_browsing_data();
        let _ = self.win.destroy();
        let account = self.account.as_deref().or(self.account_hint.as_deref());
        let payload = result_payload(
            self.mode,
            outcome,
            account,
            self.message.as_deref(),
            self.reason.as_deref(),
        );
        log::info!("signin: finished, outcome {}", outcome.wire());
        window::emit(&self.app, "signin-result", payload);
        window::focus_main(&self.app);
    }
}

#[path = "signin_session_calls.rs"]
mod calls;

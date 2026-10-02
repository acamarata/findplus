//! In-app sign-in: the session's daemon calls and its outside-close check.
//!
//! Purpose    : Split from signin_session.rs (300-line cap). Posts the token
//!              and the vault keys, opens the unlock page, and decides whether
//!              the dashboard (close_signin_window) or the daemon (a cancel
//!              recorded by any path) asked the window to close.
//! Constraints: A child module of signin_session, so it shares the private
//!              fields. The token and the keys are `take()`n into one POST.

use super::Session;
use crate::signin_close;
use crate::signin_logic as logic;
use crate::signin_machine::{token_retry, Input, Phase, TokenRetry};

/// Read the daemon's progress every this many 500 ms ticks (2 s).
const POLL_EVERY: u32 = 4;

impl Session {
    /// True when the window should close: the card asked, or the daemon says
    /// the flow was cancelled. Reads the daemon only on a Google page.
    pub(super) fn stop_asked(&mut self) -> bool {
        if signin_close::take_request() {
            return true;
        }
        if !matches!(self.phase, Phase::Waiting | Phase::Unlocking) {
            return false;
        }
        self.ticks_since_poll += 1;
        if self.ticks_since_poll < POLL_EVERY {
            return false;
        }
        self.ticks_since_poll = 0;
        let mine = self.begin.flow.clone();
        self.daemon.progress().is_some_and(|(phase, flow)| {
            let same_flow = mine.is_none() || flow.is_none() || flow == mine;
            signin_close::daemon_says_stop(self.phase, self.mode, &phase, same_flow)
        })
    }

    pub(super) fn post_token(&mut self) -> Input {
        let token = self.token.take().unwrap_or_default();
        let print = logic::fingerprint(&token);
        let retry_copy = (!self.token_retried).then(|| token.clone());
        match self.daemon.token(&self.begin.state, token) {
            Ok(reply) => {
                self.account = reply.account;
                let has_unlock_url = self.begin.unlock_url.is_some();
                Input::TokenAccepted {
                    needs_unlock: reply.needs_unlock,
                    has_unlock_url,
                }
            }
            Err(e) => match token_retry(&e.code, self.token_retried) {
                TokenRetry::Now => {
                    self.token_retried = true;
                    self.token = retry_copy;
                    self.post_token()
                }
                TokenRetry::KeepPolling => {
                    self.rejected_token = Some(print);
                    Input::TokenRetryLater
                }
                TokenRetry::Fail => {
                    if e.code == "google_unreachable" {
                        self.reason = Some(e.code);
                    }
                    self.message = Some(e.message);
                    Input::TokenRejected
                }
            },
        }
    }

    pub(super) fn navigate_unlock(&mut self) -> Option<Input> {
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

    pub(super) fn post_unlock(&mut self) -> Input {
        let keys = self.vault.take().unwrap_or_default();
        match self
            .daemon
            .unlock(&self.begin.state, keys, self.account_hint.as_deref())
        {
            Ok(()) => Input::UnlockStored,
            Err(e) => {
                self.message = Some(e.message);
                Input::UnlockRejected
            }
        }
    }
}

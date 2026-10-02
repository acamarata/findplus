//! In-app sign-in: the state machine (pure, no Tauri, no network).
//!
//! Purpose    : One reducer decides what happens next in the sign-in window,
//!              so every path (success, unlock, blocked, cancel, timeout,
//!              error) is unit-tested without a webview.
//! Inputs     : The current `Phase`, the `Mode` the window was opened in, and
//!              one `Input` the window or the daemon produced.
//! Outputs    : The next `Phase` and one `Effect` for signin_window.rs to run.
//! Constraints: `Done` is terminal: every input after it is ignored, so a late
//!              cookie or a second close can never run an effect twice.

/// Why the window was opened.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    /// Sign in with EmbeddedSetup, then unlock in the same window if needed.
    Signin,
    /// Already signed in; only unlock the end-to-end encrypted locations.
    Unlock,
}

impl Mode {
    /// The wire spelling (`mode` in events and in the daemon's begin body).
    pub fn wire(self) -> &'static str {
        match self {
            Mode::Signin => "signin",
            Mode::Unlock => "unlock",
        }
    }

    /// Pure: parse the command/deep-link spelling. Absent means sign in.
    pub fn parse(s: Option<&str>) -> Option<Mode> {
        match s.unwrap_or("signin") {
            "signin" => Some(Mode::Signin),
            "unlock" => Some(Mode::Unlock),
            _ => None,
        }
    }
}

/// The failed reason for an unlock-only window that could not read the account.
pub const ACCOUNT_UNKNOWN: &str = "account_unknown";
/// Failed reasons the shell itself knows (native_messages.FAILED_REASONS);
/// any other error is reported as "other".
const SHELL_FAILED_REASONS: &[&str] = &[ACCOUNT_UNKNOWN, "google_unreachable"];
/// The card's words for it (the daemon's native_messages.MSG_ACCOUNT_UNKNOWN).
pub const MSG_ACCOUNT_UNKNOWN: &str = "Find+ could not tell which Google account the window is signed in to, so it saved nothing. Try again.";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    /// Google's page is showing; the person is signing in.
    Waiting,
    /// The token is being exchanged by the daemon.
    Finishing,
    /// The unlock page is showing.
    Unlocking,
    /// The vault keys are being stored by the daemon.
    Storing,
    Done,
}

impl Phase {
    /// The `phase` string sent to the dashboard in `signin-progress`.
    pub fn wire(self) -> &'static str {
        match self {
            Phase::Waiting => "waiting",
            Phase::Finishing | Phase::Storing => "finishing",
            Phase::Unlocking => "unlock",
            Phase::Done => "done",
        }
    }
}

/// How the window ended. `outcome` strings are the `signin-result` contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Success { unlocked: bool },
    BlockedEmbedded,
    Cancelled,
    Timeout,
    Error,
}

impl Outcome {
    pub fn wire(self) -> &'static str {
        match self {
            Outcome::Success { .. } => "success",
            Outcome::BlockedEmbedded => "blocked_embedded",
            Outcome::Cancelled => "cancelled",
            Outcome::Timeout => "timeout",
            Outcome::Error => "error",
        }
    }

    /// The daemon `event` route's word and reason for this ending (spec
    /// §2.2; reasons are native_messages.BLOCKED_REASONS / FAILED_REASONS).
    /// An error carries its reason only when it is one the shell itself
    /// found (`account_unknown`); every other error is "other".
    pub fn daemon_event(self, reason: Option<&str>) -> (&'static str, Option<&str>) {
        match self {
            Outcome::Success { .. } | Outcome::Cancelled => ("closed", None),
            Outcome::Timeout => ("failed", Some("timeout")),
            Outcome::BlockedEmbedded => ("blocked", Some(reason.unwrap_or("other"))),
            Outcome::Error => (
                "failed",
                Some(
                    reason
                        .filter(|r| SHELL_FAILED_REASONS.contains(r))
                        .unwrap_or("other"),
                ),
            ),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Input {
    /// A live `oauth_token` cookie is in the window's store.
    CookieFound,
    TokenAccepted {
        needs_unlock: bool,
        has_unlock_url: bool,
    },
    TokenRejected,
    /// The daemon called the cookie malformed: keep waiting for a new one.
    TokenRetryLater,
    /// A main-frame page finished loading.
    PageLoaded {
        blocked: bool,
    },
    /// Unlock-only mode: the account page reported which Google account is
    /// signed in.
    AccountKnown,
    /// Unlock-only mode: the account page showed no address (or took too
    /// long). Find+ cannot tell whose keys the unlock page would give, so it
    /// stops before the unlock page (r12 #1).
    AccountUnknown,
    /// The page is a rejection page, or the sign-in left Google.
    Blocked,
    VaultKeys,
    BridgeClose,
    /// Window closed, Cmd+W, or the bridge's cancel message.
    UserClosed,
    UnlockStored,
    UnlockRejected,
    TimedOut,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Effect {
    None,
    PostToken,
    NavigateUnlock,
    PostUnlock,
    Finish(Outcome),
}

/// Pure: end the window early. In sign-in mode the unlock page comes after a
/// successful sign-in, so leaving it still counts as signed in (locked).
fn early_end(phase: Phase, mode: Mode, o: Outcome) -> (Phase, Effect) {
    let signed_in = mode == Mode::Signin && matches!(phase, Phase::Unlocking | Phase::Storing);
    let o = if signed_in {
        Outcome::Success { unlocked: false }
    } else {
        o
    };
    (Phase::Done, Effect::Finish(o))
}

/// Pure: what follows an accepted token.
fn after_token(needs_unlock: bool, has_unlock_url: bool) -> (Phase, Effect) {
    if needs_unlock && has_unlock_url {
        (Phase::Unlocking, Effect::NavigateUnlock)
    } else {
        (
            Phase::Done,
            Effect::Finish(Outcome::Success {
                unlocked: !needs_unlock,
            }),
        )
    }
}

/// Pure: one step of the machine.
pub fn step(phase: Phase, mode: Mode, input: &Input) -> (Phase, Effect) {
    use Input as I;
    use Phase as P;
    let done = |o: Outcome| (P::Done, Effect::Finish(o));
    match (phase, input) {
        (P::Done, _) => (P::Done, Effect::None),
        (_, I::UserClosed) => early_end(phase, mode, Outcome::Cancelled),
        (_, I::TimedOut) => early_end(phase, mode, Outcome::Timeout),
        (_, I::Failed) => done(Outcome::Error),
        (P::Waiting | P::Unlocking, I::Blocked | I::PageLoaded { blocked: true }) => {
            early_end(phase, mode, Outcome::BlockedEmbedded)
        }
        (P::Waiting, I::CookieFound) if mode == Mode::Signin => (P::Finishing, Effect::PostToken),
        (P::Waiting, I::AccountKnown) if mode == Mode::Unlock => {
            (P::Unlocking, Effect::NavigateUnlock)
        }
        (P::Waiting, I::AccountUnknown) if mode == Mode::Unlock => done(Outcome::Error),
        (
            P::Finishing,
            I::TokenAccepted {
                needs_unlock,
                has_unlock_url,
            },
        ) => after_token(*needs_unlock, *has_unlock_url),
        (P::Finishing, I::TokenRejected) => done(Outcome::Error),
        (P::Finishing, I::TokenRetryLater) => (P::Waiting, Effect::None),
        (P::Unlocking, I::VaultKeys) => (P::Storing, Effect::PostUnlock),
        (P::Unlocking, I::BridgeClose) => early_end(phase, mode, Outcome::Cancelled),
        (P::Storing, I::UnlockStored) => done(Outcome::Success { unlocked: true }),
        (P::Storing, I::UnlockRejected) => done(Outcome::Error),
        _ => (phase, Effect::None),
    }
}

/// What to do after the daemon refused a token (contract §3.2).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenRetry {
    /// Google did not answer (502): post the same token once more.
    Now,
    /// Not an oauth2_4 value (422): keep reading the cookie store.
    KeepPolling,
    Fail,
}

/// Pure: the retry rule for one refused token post.
pub fn token_retry(code: &str, already_retried: bool) -> TokenRetry {
    match code {
        "google_unreachable" if !already_retried => TokenRetry::Now,
        "token_malformed" => TokenRetry::KeepPolling,
        _ => TokenRetry::Fail,
    }
}

/// Pure: the `signin-result` payload. Only plain facts: never a token, a
/// cookie or a key (the caller has none to pass in).
pub fn result_payload(
    mode: Mode,
    outcome: Outcome,
    account: Option<&str>,
    message: Option<&str>,
    reason: Option<&str>,
) -> serde_json::Value {
    let mut p =
        serde_json::json!({ "provider": "google", "mode": mode.wire(), "outcome": outcome.wire() });
    if let Outcome::Success { unlocked } = outcome {
        p["unlocked"] = unlocked.into();
        p["account"] = account.into();
    }
    if let Some(m) = message {
        p["message"] = m.into();
    }
    if let Some(r) = reason.filter(|_| outcome == Outcome::BlockedEmbedded) {
        p["reason"] = r.into();
    }
    p
}

#[cfg(test)]
#[path = "signin_machine_tests.rs"]
mod tests;

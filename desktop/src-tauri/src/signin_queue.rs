//! In-app sign-in: the current flow id and a begin handed over mid-session.
//!
//! Purpose    : The daemon's progress is the one truth (contract §3.8); the
//!              shell only reports. Every `signin-progress` / `signin-result`
//!              event carries the daemon's `flow` id, so the card can ignore
//!              an older window's news. A begin the card hands over while a
//!              window is still closing is held and run next, never dropped
//!              (dropping it left the card waiting on a window that never
//!              opened, r12 #3).
//! Inputs     : `set_flow` from signin_start.rs; `hold` / `take` from
//!              signin_window.rs.
//! Outputs    : `with_flow(payload)`; the held begin.
//! Constraints: Pure decisions (`plan`) are unit-tested; the two statics are
//!              the only shared state and hold no secret (a begin's state is
//!              single-use and dies with its flow).

use std::sync::Mutex;

use crate::signin_machine::Mode;

static FLOW: Mutex<Option<String>> = Mutex::new(None);
static HELD: Mutex<Option<(Mode, serde_json::Value)>> = Mutex::new(None);

/// The flow this shell's window works for (from the daemon's begin).
pub fn set_flow(flow: Option<String>) {
    if let Ok(mut f) = FLOW.lock() {
        *f = flow;
    }
}

fn flow() -> Option<String> {
    FLOW.lock().ok().and_then(|f| f.clone())
}

/// Pure: add `"flow"` to an event payload (null when unknown).
pub fn add_flow(mut payload: serde_json::Value, flow: Option<&str>) -> serde_json::Value {
    if let Some(obj) = payload.as_object_mut() {
        obj.insert("flow".into(), flow.into());
    }
    payload
}

/// The payload with the current flow id.
pub fn with_flow(payload: serde_json::Value) -> serde_json::Value {
    add_flow(payload, flow().as_deref())
}

/// What `open` does with one request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OpenPlan {
    /// No window and no session: start one.
    Start,
    /// A window or session exists: bring it forward.
    Focus,
    /// A session is ending and the card handed a fresh begin: run it next.
    FocusAndHold,
}

/// Pure: decide one `open` call.
pub fn plan(window_or_session: bool, handed_begin: bool) -> OpenPlan {
    match (window_or_session, handed_begin) {
        (false, _) => OpenPlan::Start,
        (true, false) => OpenPlan::Focus,
        (true, true) => OpenPlan::FocusAndHold,
    }
}

/// Keep a handed begin for the next session (the newest one wins).
pub fn hold(mode: Mode, begin: serde_json::Value) {
    if let Ok(mut h) = HELD.lock() {
        *h = Some((mode, begin));
    }
}

/// The held begin, once.
pub fn take() -> Option<(Mode, serde_json::Value)> {
    HELD.lock().ok().and_then(|mut h| h.take())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn events_carry_the_flow_id() {
        let p = add_flow(json!({"provider": "google"}), Some("abc123"));
        assert_eq!(p["flow"], "abc123");
        assert_eq!(add_flow(json!({}), None)["flow"], serde_json::Value::Null);
        assert_eq!(add_flow(json!(null), Some("x")), json!(null));
    }

    #[test]
    fn a_handed_begin_is_never_dropped() {
        assert_eq!(plan(false, true), OpenPlan::Start);
        assert_eq!(plan(false, false), OpenPlan::Start);
        assert_eq!(plan(true, false), OpenPlan::Focus);
        assert_eq!(plan(true, true), OpenPlan::FocusAndHold);
    }

    #[test]
    fn the_held_begin_is_taken_once_and_the_newest_wins() {
        let _ = take();
        hold(Mode::Signin, json!({"state": "a"}));
        hold(Mode::Unlock, json!({"state": "b"}));
        let (mode, begin) = take().expect("held");
        assert_eq!(mode, Mode::Unlock);
        assert_eq!(begin["state"], "b");
        assert!(take().is_none());
    }
}

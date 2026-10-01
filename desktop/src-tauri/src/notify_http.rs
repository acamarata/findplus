//! HTTP helpers for the native-alert poller (split out of notify.rs for the 300-line cap).
//!
//! Purpose    : Fetch queued deliveries, ack them, and read lock/detail state from the daemon.
//! Constraints: Every lock/detail helper fails CLOSED to the generic notification; an ack
//!              failure never propagates. Behaviour is unchanged from the pre-split code.

use super::{DeliveryRow};

pub(super) fn fetch_deliveries(since: u64) -> (Option<u16>, Vec<DeliveryRow>) {
    fetch_deliveries_from(&crate::daemon::daemon_base(), since)
}

pub(super) fn fetch_deliveries_from(base: &str, since: u64) -> (Option<u16>, Vec<DeliveryRow>) {
    let client = match reqwest::blocking::Client::builder()
        .timeout(super::HTTP_TIMEOUT)
        .build()
    {
        Ok(c) => c,
        Err(_) => return (None, Vec::new()),
    };
    let url = format!("{base}/api/alerts/deliveries?since={since}&channel=native");
    match client.get(url).send() {
        Ok(resp) if resp.status().as_u16() == 200 => {
            // A body that will not parse yields an empty Vec, never a panic.
            (Some(200), resp.json::<Vec<DeliveryRow>>().unwrap_or_default())
        }
        Ok(resp) => (Some(resp.status().as_u16()), Vec::new()),
        Err(_) => (None, Vec::new()),
    }
}

pub(super) fn ack(id: u64) {
    ack_at(&crate::daemon::daemon_base(), id);
}

/// Fire and forget: a failed ack simply re-delivers next cycle, so it must never
/// propagate.
pub(super) fn ack_at(base: &str, id: u64) {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(super::HTTP_TIMEOUT)
        .build()
    else {
        return;
    };
    let _ = client
        .post(format!("{base}/api/alerts/deliveries/{id}/ack"))
        .send();
}

pub(super) fn fetch_locked() -> bool {
    fetch_locked_from(&crate::daemon::daemon_base())
}

/// EVERY failure path (unreachable, non-200, unparseable body, key absent) returns
/// true: fail closed to the generic notification, never open to real content.
pub(super) fn fetch_locked_from(base: &str) -> bool {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(super::HTTP_TIMEOUT)
        .build()
    else {
        return true;
    };
    let Ok(resp) = client.get(format!("{base}/api/lock/status")).send() else {
        return true;
    };
    if resp.status().as_u16() != 200 {
        return true;
    }
    let Ok(body) = resp.json::<serde_json::Value>() else {
        return true;
    };
    body.get("locked").and_then(|v| v.as_bool()).unwrap_or(true)
}

pub(super) fn fetch_native_detail_enabled() -> bool {
    fetch_native_detail_enabled_from(&crate::daemon::daemon_base())
}

/// Only called when fetch_locked() is false (locked already forces generic). EVERY
/// failure path returns false: fail closed to generic.
pub(super) fn fetch_native_detail_enabled_from(base: &str) -> bool {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(super::HTTP_TIMEOUT)
        .build()
    else {
        return false;
    };
    let Ok(resp) = client.get(format!("{base}/api/settings")).send() else {
        return false;
    };
    if resp.status().as_u16() != 200 {
        return false;
    }
    let Ok(body) = resp.json::<serde_json::Value>() else {
        return false;
    };
    body.get("alerts.native_detail")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

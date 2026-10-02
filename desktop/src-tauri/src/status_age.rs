//! Time helpers for the tray status line (split out of status.rs for the 300-line cap).
//!
//! Purpose    : Parse the daemon's RFC3339 timestamps without a date crate, and turn an
//!              elapsed time into "12s" / "5m" / "2h" and a stale verdict.
//! Constraints: Pure apart from `now_epoch`; behaviour is unchanged from the pre-split code.

pub(super) fn age_from_seconds(elapsed: i64) -> String {
    let elapsed = elapsed.max(0);
    if elapsed < 60 {
        format!("{elapsed}s")
    } else if elapsed < 3600 {
        format!("{}m", elapsed / 60)
    } else {
        format!("{}h", elapsed / 3600)
    }
}

pub(super) fn parse_iso(s: &str) -> Option<i64> {
    // Minimal RFC3339 -> epoch seconds without pulling in chrono/time: the
    // daemon always emits "...Z" UTC timestamps (api-contract.md), so a
    // fixed-format parse is sufficient and dependency-free.
    let s = s.trim_end_matches('Z');
    let (date, time) = s.split_once('T')?;
    let mut d = date.split('-');
    let y: i64 = d.next()?.parse().ok()?;
    let mo: i64 = d.next()?.parse().ok()?;
    let da: i64 = d.next()?.parse().ok()?;
    let time = time.split('.').next().unwrap_or(time);
    let mut t = time.split(':');
    let h: i64 = t.next()?.parse().ok()?;
    let mi: i64 = t.next()?.parse().ok()?;
    let se: i64 = t.next()?.parse().ok()?;

    // Days since epoch via a simple proleptic Gregorian calc.
    let a = (14 - mo) / 12;
    let y2 = y + 4800 - a;
    let m2 = mo + 12 * a - 3;
    let jdn = da + (153 * m2 + 2) / 5 + 365 * y2 + y2 / 4 - y2 / 100 + y2 / 400 - 32045;
    let days_since_epoch = jdn - 2440588;
    Some(days_since_epoch * 86400 + h * 3600 + mi * 60 + se)
}

pub(super) fn now_epoch() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

pub(super) fn is_stale(last_poll_at: Option<&str>, interval_min: u64) -> bool {
    let Some(ts) = last_poll_at.and_then(parse_iso) else {
        return false;
    };
    let elapsed = now_epoch() - ts;
    elapsed > (2 * interval_min as i64 * 60)
}

pub(super) fn age_string(last_poll_at: Option<&str>) -> String {
    let Some(ts) = last_poll_at.and_then(parse_iso) else {
        return "unknown".to_string();
    };
    let elapsed = (now_epoch() - ts).max(0);
    if elapsed < 60 {
        format!("{elapsed}s")
    } else if elapsed < 3600 {
        format!("{}m", elapsed / 60)
    } else {
        format!("{}h", elapsed / 3600)
    }
}

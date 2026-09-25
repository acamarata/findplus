"""Resend scheduled alert deliveries whose transient failure is due another try.

Purpose : Drain "retrying" alert_deliveries rows once their next_attempt_at is
          due: resend through the same channel, then mark sent, reschedule
          the next attempt, or give up after dispatch_core.MAX_ATTEMPTS.
Inputs  : alert_deliveries rows with status="retrying" and a due
          next_attempt_at; the rule and source event each row points at.
Outputs : Updated rows (status/attempts/next_attempt_at/error). No new rows --
          a retry never re-inserts, so the original dedup key never moves.
Constraints:
    - Runs from the same poll cycle dispatch.process() runs from (see
      poller.py's _process_alert_retries) -- no new thread.
    - Idempotent across daemon restarts: all state (attempts, next_attempt_at)
      lives on the row, never in memory, so a restart mid-backoff resumes
      from exactly where the row says it is.
    - native is never retried -- dispatch.py never writes status="retrying"
      for it (it has no send to retry, only a queue entry). Native's own
      OS-lock-screen generic-content rule (notifications.md §2) is enforced
      by desktop/src-tauri/src/notify.rs against /api/lock/status and never
      applies here for that reason.
    - A row whose rule or source event was deleted since the first failure
      (rule removed, retention pruning) cannot be resent; it is marked
      failed rather than retried forever against nothing.
    - Each call drains at most RETRY_DRAIN_LIMIT due rows, oldest-due first,
      so a large backlog after an outage cannot stall a poll cycle.
    - A retry always renders the exact text the first attempt rendered
      (render_message() is called with the row's own first-attempt time,
      never the retry's own `now`) and never resends a key a newer delivery
      already cooled down this same cycle.
    - `sent_at` only ever moves forward, and only once: to the real send
      time on the attempt that finally succeeds, so cooldowns
      (dispatch_core.in_cooldown) run from when the message actually went
      out, not from the first failure.
"""

from __future__ import annotations

import datetime

from findplus.alerts.dispatch_core import (
    MAX_ATTEMPTS,
    DeviceEvent,
    GroupEvent,
    as_utc,
    compute_next_attempt_at,
    is_transient_failure,
)
from findplus.alerts.dispatch_send import _status_for
from findplus.groups.quorum import group_event_note, stale_note_for_count
from findplus.logging_setup import get_logger

log = get_logger(__name__)

#: R2: how many due retries one poll cycle drains. Each send has its own
#: per-channel timeout (httpx `timeout=10.0` in telegram/webhook/whatsapp),
#: so an unbounded backlog after an outage would run every due row
#: synchronously in the poller thread and freeze polling for the whole
#: outage's worth of rows at once. Capping the drain lets the cycle finish
#: and the poller keep ticking; the remaining backlog drains progressively,
#: oldest-due first, over the following cycles.
RETRY_DRAIN_LIMIT = 20

#: COALESCE(d.label, d.name): a retry resolves the label the same way dispatch.py does (UAT U7).
_DEVICE_EVENT_SQL = """SELECT pe.id, pe.place_id, p.name AS place_name, pe.device_id,
       COALESCE(d.label, d.name) AS device_name, pe.event_type, pe.observed_at, pe.fetched_at,
       pe.confidence
FROM place_events pe JOIN places p ON p.id = pe.place_id
JOIN devices d ON d.device_id = pe.device_id
WHERE pe.id = :id"""

_GROUP_EVENT_SQL = """SELECT gpe.id, gpe.group_id, g.name AS group_name, gpe.place_id,
       p.name AS place_name, gpe.event_type, gpe.observed_at, gpe.confidence,
       gpe.members_crossed, gpe.members_considered, gpe.members_stale
FROM group_place_events gpe JOIN groups g ON g.id = gpe.group_id
JOIN places p ON p.id = gpe.place_id
WHERE gpe.id = :id"""


def _load_event(session, kind: str, event_id: int) -> DeviceEvent | GroupEvent | None:
    """Reload one already-notified event by id, ignoring notified_at.

    A retry's source event was stamped notified on the first attempt
    (process() stamps it regardless of outcome), so the pending-only queries
    dispatch.py uses for a fresh cycle would never find it again.
    """
    from sqlalchemy import text

    if kind == "device":
        row = session.execute(text(_DEVICE_EVENT_SQL), {"id": event_id}).first()
        if row is None:
            return None
        return DeviceEvent(
            place_event_id=row.id,
            place_id=row.place_id,
            place_name=row.place_name,
            device_id=row.device_id,
            device_name=row.device_name,
            event_type=row.event_type,
            observed_at=as_utc(row.observed_at),
            fetched_at=as_utc(row.fetched_at),
            confidence=row.confidence,
            group_ids=[],
        )
    row = session.execute(text(_GROUP_EVENT_SQL), {"id": event_id}).first()
    if row is None:
        return None
    return GroupEvent(
        group_place_event_id=row.id,
        group_id=row.group_id,
        group_name=row.group_name,
        place_id=row.place_id,
        place_name=row.place_name,
        event_type=row.event_type,
        observed_at=as_utc(row.observed_at),
        confidence=row.confidence,
        note=group_event_note(
            crossed=row.members_crossed,
            considered=row.members_considered,
            event_type=row.event_type,
            place=row.place_name,
            stale_note=stale_note_for_count(row.members_stale),
        ),
        members_crossed=row.members_crossed,
        members_considered=row.members_considered,
        members_stale=row.members_stale,
    )


def _load_rule(session, rule_id: int):
    from findplus.alerts.channels_field import parse_channels
    from findplus.alerts.dispatch_core import Rule
    from findplus.db.models_alerts import AlertRule as AlertRuleORM

    r = session.get(AlertRuleORM, rule_id)
    if r is None:
        return None
    return Rule(
        id=r.id,
        name=r.name,
        place_id=r.place_id,
        group_id=r.group_id,
        device_id=r.device_id,
        on_enter=r.on_enter,
        on_exit=r.on_exit,
        channels=parse_channels(r.channels),
        cooldown_minutes=r.cooldown_minutes,
        enabled=r.enabled,
        also_notify_members=r.also_notify_members,
    )


def _superseded_by_newer_delivery(session, row, rule, event, now: datetime.datetime) -> bool:
    """R4: true when a fresher "sent" delivery already started this exact
    cooldown key (rule, channel, event_kind, place) after this row's own
    first attempt.

    A new crossing can be matched, sent and start a cooldown in the same
    poll cycle a stale retry becomes due in (dispatch.process() runs before
    process_retries() every cycle, poller.py's _run_poll_cycle) -- resending
    the old event anyway would ignore the cooldown that same cycle just
    started. `row.sent_at` is the row's own first-attempt time (R3 only
    ever moves it forward on eventual success, never during the ladder), so
    "newer than row.sent_at" is exactly "happened after this row's own
    original failure".
    """
    if rule.cooldown_minutes == 0:
        return False
    from sqlalchemy import select

    from findplus.db.models import GroupPlaceEvent, PlaceEvent
    from findplus.db.models_alerts import AlertDelivery as AlertDeliveryORM

    model = PlaceEvent if row.event_kind == "device" else GroupPlaceEvent
    limit = now - datetime.timedelta(minutes=rule.cooldown_minutes)
    stmt = (
        select(AlertDeliveryORM.id)
        .join(model, model.id == AlertDeliveryORM.event_id)
        .filter(
            AlertDeliveryORM.rule_id == row.rule_id,
            AlertDeliveryORM.channel == row.channel,
            AlertDeliveryORM.event_kind == row.event_kind,
            AlertDeliveryORM.status == "sent",
            AlertDeliveryORM.sent_at > limit,
            AlertDeliveryORM.sent_at > row.sent_at,
            model.place_id == event.place_id,
            AlertDeliveryORM.id != row.id,
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def _retry_one(session, row, channels_cfg, now: datetime.datetime) -> None:
    """Resend one due row and update it in place. Never raises."""
    rule = _load_rule(session, row.rule_id)
    event = _load_event(session, row.event_kind, row.event_id)
    if rule is None or event is None:
        row.status = "failed"
        row.error = "rule or source event no longer exists"
        row.next_attempt_at = None
        return

    if _superseded_by_newer_delivery(session, row, rule, event, now):
        # R4: a newer send already cooled this key down this same cycle --
        # resending the stale one would double-notify at the same key.
        row.status = "skipped"
        row.error = "superseded by a newer delivery in the same cooldown window"
        row.next_attempt_at = None
        return

    # R7: render with the row's own first-attempt time, not this retry's
    # `now` -- render_message()'s only time-dependent choice (same-day vs.
    # full-date formatting) must not drift attempt to attempt; a retry
    # sends the exact text the first attempt would have. `now` below (the
    # real current time) is still used for the retry ladder's own math.
    status, err, status_code, retry_after = _status_for(
        row.channel, rule, event, row.event_kind, channels_cfg, row.sent_at, row.target
    )
    row.attempts += 1
    if status == "sent":
        # R3: cooldowns are keyed on `sent_at` (dispatch_core.in_cooldown) --
        # leaving the first failure's timestamp here would let the next
        # crossing fire before the real cooldown window has actually passed.
        row.status, row.error, row.next_attempt_at, row.sent_at = "sent", None, None, now
        return
    retryable = status == "failed" and is_transient_failure(status_code, err)
    if retryable and row.attempts < MAX_ATTEMPTS:
        row.status = "retrying"
        row.error = err
        row.next_attempt_at = compute_next_attempt_at(row.sent_at, row.attempts, now, retry_after)
        return
    # R5: `status` here is "failed" or "skipped" (e.g. the channel was
    # removed/unconfigured during backoff, dispatch_send.py's
    # channel-not-configured branch) -- never force it to "failed".
    row.status, row.error, row.next_attempt_at = status, err, None


def process_retries(session, now: datetime.datetime | None = None) -> int:
    """Resend up to RETRY_DRAIN_LIMIT due retries, oldest-due first.

    Returns how many rows were processed this call. A backlog larger than
    the limit is left `status="retrying"` with `next_attempt_at` already in
    the past -- the very next call (the next poll cycle) picks up where this
    one stopped, oldest first, so the drain always makes forward progress
    without ever blocking a cycle on the whole backlog (R2).
    """
    from sqlalchemy import select

    from findplus.alerts.store import load_alerts
    from findplus.db.models_alerts import AlertDelivery as AlertDeliveryORM

    now = now or datetime.datetime.now(datetime.UTC)
    stmt = (
        select(AlertDeliveryORM)
        .filter(AlertDeliveryORM.status == "retrying", AlertDeliveryORM.next_attempt_at <= now)
        .order_by(AlertDeliveryORM.next_attempt_at.asc())
        .limit(RETRY_DRAIN_LIMIT)
    )
    rows = session.execute(stmt).scalars().all()
    if not rows:
        return 0
    channels_cfg = load_alerts()
    for row in rows:
        try:
            _retry_one(session, row, channels_cfg, now)
        except Exception:
            log.exception("alert_retry_failed", delivery_id=row.id)
            row.status = "failed"
            row.error = "retry raised an unexpected error"
            row.next_attempt_at = None
    session.commit()
    return len(rows)

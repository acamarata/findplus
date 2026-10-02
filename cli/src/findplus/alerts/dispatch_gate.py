"""What dispatch may send now: no history, no events from before a rule, no floods.

Purpose : uat116 #1. Switching alerts on over 21 days of un-notified history
          sent 390 Telegram messages in one burst. Three gates stop that:
            1. Age. An event is news only while it is fresh: at most
               MAX_AGE minutes (setting alerts.max_age_minutes, default 30)
               after Find+ first fetched the sighting, and never more than
               MAX_OBSERVED_HOURS after it happened. Find Hub reports are
               often 10 to 40 minutes late (honesty.ALERTS_LATENCY), so the
               fetch time, not the crossing time, decides "fresh": a crossing
               reported 25 minutes late still alerts, with its time.
            2. Rule age. A rule never sends an event that happened before the
               rule was created.
            3. Burst. At most BURST_LIMIT messages per chat per BURST_WINDOW;
               the rest are recorded as skipped and summed up in ONE message.
          Skipped events are still stamped notified by dispatch.process, so
          they never come back. Each skip is logged.
Inputs  : Dispatch events, rules, the session (settings and recent rows).
Outputs : Filtered event lists; per-target burst counters; one summary send.
Constraints: Never raises into dispatch: the summary send is wrapped.
"""

from __future__ import annotations

import datetime

from findplus.alerts.dispatch_types import LeftBehindEvent, Rule
from findplus.logging_setup import get_logger

log = get_logger(__name__)

MAX_AGE_SETTING = "alerts.max_age_minutes"
MAX_AGE_MINUTES = 30
MAX_OBSERVED_HOURS = 2
BURST_LIMIT = 5
BURST_WINDOW = datetime.timedelta(minutes=1)
#: Channels that speak to one chat at a time and can be flooded.
BURST_CHANNELS = ("telegram", "whatsapp")


def _utc(value):
    from findplus.alerts.dispatch_core import as_utc

    return as_utc(value)


def happened_at(event) -> datetime.datetime:
    """When the event became true: a left-behind episode when it was confirmed."""
    if isinstance(event, LeftBehindEvent) and event.decided_at is not None:
        return _utc(event.decided_at)
    return _utc(event.observed_at)


def learned_at(event) -> datetime.datetime:
    """When Find+ learned of it: the first fetch of the deciding sighting."""
    if isinstance(event, LeftBehindEvent) and event.decided_at is not None:
        return _utc(event.decided_at)
    fetched = getattr(event, "fetched_at", None)
    return _utc(fetched) if fetched is not None else _utc(event.observed_at)


def max_age_minutes(session) -> int:
    from findplus.state import get_setting

    raw = get_setting(session, MAX_AGE_SETTING, str(MAX_AGE_MINUTES))
    try:
        return max(1, int(raw or MAX_AGE_MINUTES))
    except ValueError:
        return MAX_AGE_MINUTES


def is_stale(event, now: datetime.datetime, max_age: int) -> bool:
    """Too old to be news (gate 1)."""
    if now - learned_at(event) > datetime.timedelta(minutes=max_age):
        return True
    return now - happened_at(event) > datetime.timedelta(hours=MAX_OBSERVED_HOURS)


def fresh_events(session, events: list, now: datetime.datetime) -> list:
    """The events still worth sending; the rest are logged and left to be stamped."""
    max_age = max_age_minutes(session)
    fresh = [e for e in events if not is_stale(e, now, max_age)]
    skipped = len(events) - len(fresh)
    if skipped:
        log.info("alert_events_too_old", skipped=skipped, max_age_minutes=max_age)
    return fresh


def predates(rule: Rule, event) -> bool:
    """The event happened before the rule existed (gate 2)."""
    created = _utc(rule.created_at) if rule.created_at is not None else None
    return created is not None and happened_at(event) < created


class Burst:
    """Per-(channel, target) send counter for this run, seeded from recent rows."""

    def __init__(self, session, now: datetime.datetime) -> None:
        self._session = session
        self._now = now
        self._sent: dict[tuple[str, str], int] = {}
        self.held: dict[tuple[str, str], int] = {}

    def _recent(self, channel: str, target: str) -> int:
        from findplus.db.models_alerts import AlertDelivery

        since = self._now - BURST_WINDOW
        q = self._session.query(AlertDelivery).filter(
            AlertDelivery.channel == channel,
            AlertDelivery.target == target,
            AlertDelivery.sent_at > since,
            AlertDelivery.status != "skipped",
        )
        return q.count()

    def full(self, channel: str, target: str) -> bool:
        if channel not in BURST_CHANNELS:
            return False
        key = (channel, target)
        if key not in self._sent:
            self._sent[key] = self._recent(channel, target)
        return self._sent[key] >= BURST_LIMIT

    def note_sent(self, channel: str, target: str) -> None:
        key = (channel, target)
        self._sent[key] = self._sent.get(key, 0) + 1

    def hold(self, channel: str, target: str) -> None:
        key = (channel, target)
        self.held[key] = self.held.get(key, 0) + 1


def send_summaries(burst: Burst, channels_cfg) -> None:
    """One "N more happened earlier" message per chat that hit the limit."""
    from findplus.people.messages import t

    for (channel, target), count in burst.held.items():
        text = t("msg.burstOne") if count == 1 else t("msg.burstMore", count=count)
        try:
            ok = _send_text(channel, target, text, channels_cfg)
        except Exception as exc:  # a summary failure must never crash dispatch
            ok = False
            log.warning("alert_burst_summary_failed", channel=channel, error=type(exc).__name__)
        log.info("alert_burst_summarised", channel=channel, held=count, sent=bool(ok))


def _send_text(channel: str, target: str, text: str, channels_cfg) -> bool:
    if channel == "telegram" and channels_cfg.telegram:
        from findplus.alerts.channels.telegram import send

        chat = target or (channels_cfg.telegram.chat_ids or [None])[0]
        return bool(chat) and send(text, channels_cfg.telegram.bot_token, chat).success
    if channel == "whatsapp" and getattr(channels_cfg, "whatsapp", None):
        from findplus.alerts.channels.whatsapp_callmebot import send

        wa = channels_cfg.whatsapp
        return send(text, wa.phone, wa.apikey).success
    return False

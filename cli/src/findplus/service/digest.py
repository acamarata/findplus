"""The evening summary: a scheduler that sends each person's day once (spec § 7.2).

Purpose    : At the time set in `people.digest` (default 20:00, off until the
             owner turns it on) send each chosen person's day summary to the
             connected channel. One `digest_runs` row per (person, local date,
             channel, target) makes a restart, a second daemon tick or a slow
             network unable to send twice.
Inputs     : The `people.digest` preference, the person/pet groups, the stored
             Telegram credentials, a clock, the computer's local zone and a
             sender. All of them are injectable, so tests use a fake
             clock and a fake channel and never touch the network.
Outputs    : `Outcome` rows from `tick()`; `digest_runs` rows; log lines.
Constraints: Sends while the app is locked, like alerts do: the lock protects
             what this computer shows, and the daemon keeps running. A day with
             nothing tracked sends nothing, unless the owner chose "always send". A
             failed send is retried once on the next tick, then recorded as
             failed. A crash mid-send is never resent: the claim row stays.
             Statuses: sending, sent, skipped, retry, failed. `sent_at` is the
             time of the last attempt. A day skipped for having no data is
             looked at again every SKIP_RECHECK that evening and, until noon,
             the next morning, so a first sighting that arrives after the send
             time still gets its summary; a sent day is never sent twice.
             By default the whole family goes in one message per chat (service/digest_combined.py).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Group
from findplus.db.models_people import PERSON_KINDS, DigestRun
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger
from findplus.people import digest_prefs
from findplus.people.day_load import day_payload
from findplus.people.day_render import render_text
from findplus.service.digest_send import Sender, SendOutcome, send_to_targets, telegram_creds

log = get_logger(__name__)

TICK_SECONDS = 60.0
#: A retry waits at least this long after the failed attempt.
RETRY_AFTER = timedelta(seconds=55)
#: A claim older than this with no result means the process died mid-send.
STALE_CLAIM = timedelta(minutes=15)
#: A day skipped as "nothing tracked" is looked at again no sooner than this.
SKIP_RECHECK = timedelta(minutes=15)
#: Until this local hour the day before is still re-checked for a late first sighting.
MORNING_RETRY_UNTIL_HOUR = 12
DONE = ("sent", "skipped", "failed", "sending")


@dataclass(frozen=True)
class Outcome:
    person_id: int | None
    target: str
    status: str  # sent | skipped | retry | failed | no_channel
    error: str | None = None


def _local_zone() -> ZoneInfo | None:
    from findplus.timeline import local_zone

    return local_zone()


def _people(session: Session, prefs: dict) -> list[Group]:
    stmt = select(Group).where(Group.kind.in_(PERSON_KINDS)).order_by(Group.name)
    if prefs["people"]:
        stmt = stmt.where(Group.id.in_(prefs["people"]))
    return list(session.scalars(stmt).all())


class DigestScheduler:
    """Calls `tick()` every minute until `stop()`."""

    def __init__(
        self,
        state_dir: Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        tz: ZoneInfo | None = None,
        sender: Sender | None = None,
        channels_loader: Callable[[], object] | None = None,
        interval: float = TICK_SECONDS,
    ) -> None:
        self._state_dir = state_dir
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tz = tz
        self._sender = sender
        self._channels = channels_loader
        self._interval = interval
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        log.info("digest_scheduler_started")
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # a bad tick must not end the schedule
                log.warning("digest_tick_failed", error=str(exc))
            self._stop.wait(self._interval)
        log.info("digest_scheduler_stopped")

    # ------------------------------------------------------------------ tick
    def tick(self, now: datetime | None = None) -> list[Outcome]:
        """Send what is due. Returns one Outcome per (person, target) handled."""
        now = (now or self._clock()).astimezone(UTC)
        tz = self._tz or _local_zone()
        with session_scope() as s:
            prefs = digest_prefs.load(s)
            if not prefs["enabled"]:
                return []
            self._expire_claims(s, now)
        local = now.astimezone(tz)
        hour, minute = digest_prefs.hour_minute(prefs)
        due = local >= local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        morning = local.hour < MORNING_RETRY_UNTIL_HOUR
        if not due and not morning:
            return []
        creds = telegram_creds(prefs["channel"], self._channels() if self._channels else None)
        out: list[Outcome] = []
        if creds is not None and morning:
            yesterday = local.date() - timedelta(days=1)
            out += self._run_people(prefs, creds, yesterday, tz, now, retry_only=True)
        if not due:
            return out
        if creds is None:
            return [Outcome(None, "", "no_channel")]
        return out + self._run_people(prefs, creds, local.date(), tz, now)

    @staticmethod
    def _expire_claims(session: Session, now: datetime) -> None:
        rows = session.scalars(select(DigestRun).where(DigestRun.status == "sending")).all()
        for row in rows:
            if row.sent_at is None or now - row.sent_at > STALE_CLAIM:
                row.status, row.error = "failed", "interrupted before it finished"
                log.warning("digest_claim_expired", group_id=row.group_id, date=row.local_date)

    def _run_people(self, prefs, creds, day, tz, now, retry_only: bool = False) -> list[Outcome]:
        with session_scope() as s:
            ids = [(g.id, g.name) for g in _people(s, prefs)]
        if prefs.get("combined", True):
            from findplus.service.digest_combined import run_combined

            return run_combined(self, [i for i, _ in ids], prefs, creds, day, tz, now, retry_only)
        out: list[Outcome] = []
        for group_id, _name in ids:
            out += self._one_person(group_id, prefs, creds, day, tz, now, retry_only)
        return out

    def _pending_targets(
        self, group_id: int, day, creds, now, retry_only: bool = False
    ) -> list[str]:
        """Chats still owed this day. A skipped (no data) day comes back after SKIP_RECHECK;
        `retry_only` (the morning pass over yesterday) never starts a day, only reopens one."""
        with session_scope() as s:
            rows = {
                r.target: r
                for r in s.scalars(
                    select(DigestRun).where(
                        DigestRun.group_id == group_id,
                        DigestRun.local_date == day.isoformat(),
                        DigestRun.channel == "telegram",
                    )
                ).all()
            }
        todo = []
        for chat in creds.chat_ids:
            row = rows.get(chat)
            if row is None:
                if not retry_only:
                    todo.append(chat)
            elif row.sent_at and (
                (row.status == "retry" and now - row.sent_at >= RETRY_AFTER)
                or (row.status == "skipped" and now - row.sent_at >= SKIP_RECHECK)
            ):
                todo.append(chat)
        return todo

    def _one_person(self, group_id, prefs, creds, day, tz, now, retry_only=False) -> list[Outcome]:
        targets = self._pending_targets(group_id, day, creds, now, retry_only)
        if not targets:
            return []
        with session_scope() as s:
            group = s.get(Group, group_id)
            if group is None:
                return []
            payload = day_payload(s, group, day, tz, now)
        if payload["empty"] and not prefs["always_send"]:
            return [
                self._record(group_id, day, t, "skipped", now, "nothing tracked") for t in targets
            ]
        text = render_text(payload)
        for chat in targets:
            self._claim(group_id, day, chat, now)
        results = send_to_targets(text, creds, self._sender, targets)
        return [self._finish(group_id, day, r, now) for r in results]

    # ------------------------------------------------------------- the rows
    @staticmethod
    def _claim(group_id: int, day, target: str, now: datetime) -> None:
        with session_scope() as s:
            row = s.scalar(
                select(DigestRun).where(
                    DigestRun.group_id == group_id,
                    DigestRun.local_date == day.isoformat(),
                    DigestRun.channel == "telegram",
                    DigestRun.target == target,
                )
            )
            if row is None:
                s.add(
                    DigestRun(
                        group_id=group_id,
                        local_date=day.isoformat(),
                        channel="telegram",
                        target=target,
                        status="sending",
                        sent_at=now,
                    )
                )
            else:
                if row.status == "skipped":
                    row.error = None  # a first real attempt: a failure still gets its one retry
                row.status, row.sent_at = "sending", now

    @staticmethod
    def _record(group_id, day, target, status, now, error=None) -> Outcome:
        with session_scope() as s:
            row = s.scalar(
                select(DigestRun).where(
                    DigestRun.group_id == group_id,
                    DigestRun.local_date == day.isoformat(),
                    DigestRun.channel == "telegram",
                    DigestRun.target == target,
                )
            )
            if row is None:
                s.add(
                    DigestRun(
                        group_id=group_id,
                        local_date=day.isoformat(),
                        channel="telegram",
                        target=target,
                        status=status,
                        sent_at=now,
                        error=error,
                    )
                )
            else:  # a skipped day looked at again and still empty
                row.status, row.sent_at, row.error = status, now, error
        return Outcome(group_id, target, status, error)

    @staticmethod
    def _finish(group_id: int, day, result: SendOutcome, now: datetime) -> Outcome:
        with session_scope() as s:
            row = s.scalar(
                select(DigestRun).where(
                    DigestRun.group_id == group_id,
                    DigestRun.local_date == day.isoformat(),
                    DigestRun.channel == "telegram",
                    DigestRun.target == result.target,
                )
            )
            first_try = row is not None and row.error is None
            retry = "retry" if first_try else "failed"
            status = "sent" if result.ok else retry
            if row is not None:
                row.status, row.sent_at, row.error = status, now, result.error
        if not result.ok:
            log.warning("digest_send_failed", group_id=group_id, status=status, error=result.error)
        return Outcome(group_id, result.target, status, result.error)

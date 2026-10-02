"""Shared pieces for the digest, day API and day CLI tests (package C).

Purpose : A Telegram connection on disk, a fake sender that records messages,
          and a seeded school day for one person. No network, no real state dir.
Inputs  : The tmp_db-backed fixtures of cli/tests/conftest.py.
Outputs : n/a (test-only; never imported by cli/src).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from findplus.alerts.store import TelegramCreds, save_channel
from findplus.db.session import session_scope

from ._day_helpers import lean_school_day
from ._helpers import Timeline, seed_person, seed_places

TOKEN = "123456:" + "A" * 35


@dataclass
class FakeResult:
    success: bool = True
    error: str | None = None
    status_code: int | None = 200


@dataclass
class FakeChannel:
    """Records (text, chat) sends; `fail` is how many sends fail before they succeed."""

    sent: list = field(default_factory=list)
    fail: int = 0

    def __call__(self, text: str, token: str, chat_id: str):
        self.sent.append((text, token, chat_id))
        if self.fail > 0:
            self.fail -= 1
            return FakeResult(False, "telegram: HTTP 500")
        return FakeResult()


def connect_telegram(chats=("42",)) -> None:
    save_channel(
        telegram=TelegramCreds(
            TOKEN, tuple(chats), "Family", "findplus_bot", "2026-09-01T00:00:00Z"
        )
    )


def seed_school_day(names=("Sam",)) -> list[int]:
    """Home/School places and one person with a full school day on 2026-09-21 (UTC)."""
    with session_scope() as s:
        seed_places(s)
        ids = [seed_person(s, n).id for n in names[:1]]
        lean_school_day(Timeline()).ingest(s)
    return ids

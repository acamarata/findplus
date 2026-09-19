"""Fake LocationProvider and DB helpers shared by the poller test modules.

Purpose    : One definition of the fake provider and the two poll_runs /
             observation-count helpers, used by test_poller.py and
             test_poller_providers.py (test_poller.py was 416 lines, over the
             PRI 300-line rule, which applies to test files too).
Constraints: never touches the network, the real account or the real state dir.
             The `register_provider` and `selected` FIXTURES live in
             cli/tests/conftest.py, not here.
"""

from __future__ import annotations

from sqlalchemy import desc, func, select

from findplus.db.models import LocationObservation, PollRun


class FakeProvider:
    """Stands in for a LocationProvider. Never touches the network."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result if result is not None else []
        self.error = error
        self.calls = 0

    def locate(self, device_id: str, device_name: str):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def is_available(self) -> tuple[bool, str]:
        return (True, "")

    def is_authenticated(self) -> bool:
        return True

    def authenticate(self, interactive: bool = True) -> str:
        return "ok"

    def describe_auth(self) -> dict:
        return {}

    def list_devices(self) -> list:
        return []


class _UnavailableProvider(FakeProvider):
    def is_available(self) -> tuple[bool, str]:
        return (False, "offline")


class _UnauthedProvider(FakeProvider):
    def is_authenticated(self) -> bool:
        return False


def _last_run():
    from findplus.db.session import session_scope

    with session_scope() as session:
        return session.scalar(select(PollRun).order_by(desc(PollRun.started_at)).limit(1))


def _obs_count() -> int:
    from findplus.db.session import session_scope

    with session_scope() as session:
        return int(session.scalar(select(func.count(LocationObservation.id))) or 0)

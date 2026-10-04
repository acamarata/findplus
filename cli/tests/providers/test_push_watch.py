"""The upstream push client can shut itself down; the next poll must restart it.

Live install 2026-10-04: three SSL close errors made FcmPushClient stop, upstream's
FcmReceiver kept `_listening = True`, and every later poll waited 90 s for nothing
until the app restarted. Each poll also left its callback registered for good.
"""

from __future__ import annotations

import asyncio
import threading
from enum import Enum

from findplus.providers.google_findhub.push_watch import ensure_listening, forget_callback


class _State(Enum):
    STARTED = 5
    STOPPING = 7


class _FakePushClient:
    def __init__(self) -> None:
        self.do_listen = True
        self.run_state = _State.STARTED
        self.sequential_error_counters = {"CONNECTION": 3}
        self.starts = 0

    async def start(self) -> None:
        self.starts += 1
        self.do_listen = True
        self.run_state = _State.STARTED


class _FakeReceiver:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._loop_thread.start()
        self._listening = True
        self.pc = _FakePushClient()
        self.location_update_callbacks: list = []

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=5)
        self._loop.close()


def test_a_live_push_client_is_left_alone() -> None:
    receiver = _FakeReceiver()
    try:
        assert ensure_listening(receiver) == "ok"
        assert receiver.pc.starts == 0
    finally:
        receiver.close()


def test_a_push_client_that_gave_up_is_restarted_with_fresh_counters() -> None:
    receiver = _FakeReceiver()
    receiver.pc.do_listen = False
    receiver.pc.run_state = _State.STOPPING
    try:
        assert ensure_listening(receiver) == "restarted"
        assert receiver.pc.starts == 1
        assert receiver.pc.run_state is _State.STARTED
        assert receiver.pc.sequential_error_counters == {}
    finally:
        receiver.close()


def test_a_dead_loop_thread_makes_the_next_registration_start_over() -> None:
    receiver = _FakeReceiver()
    receiver.close()
    assert ensure_listening(receiver) == "relaunch"
    assert receiver._listening is False


def test_a_receiver_that_never_started_is_left_to_upstream() -> None:
    class _Fresh:
        _listening = False

    assert ensure_listening(_Fresh()) == "ok"


def test_each_poll_removes_its_own_callback_once() -> None:
    receiver = _FakeReceiver()
    receiver.close()

    def mine(_: str) -> None: ...

    def other(_: str) -> None: ...

    receiver.location_update_callbacks += [other, mine]
    forget_callback(receiver, mine)
    forget_callback(receiver, mine)  # a second call is harmless
    assert receiver.location_update_callbacks == [other]

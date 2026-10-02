"""Past days learn new people and places, without sending anything (uat116 #4).

The wizard order: trackers are polled first, then places are saved, then people
are accepted. Every past day must still read "left Home" / "arrived at School",
and GET /api/people/replay says how far the replay got.
"""

from __future__ import annotations

from unittest.mock import patch

from findplus.db.models import GroupPlaceEvent
from findplus.db.session import session_scope
from findplus.people import replay
from findplus.state import track_devices

from ._day_helpers import lean_school_day
from ._helpers import HOME, SAM, SCHOOL, Timeline, at, seed_person


def _history_only(tmp_db):
    with session_scope() as s:
        from findplus.ingest import upsert_device

        for device_id, name in SAM.items():
            upsert_device(s, device_id, name, provider="test-fake", now=at(0, 0, day=-1))
        track_devices(s, list(SAM))
        lean_school_day(Timeline()).ingest(s)


def _place(client, name, where, kind):
    body = {"name": name, "latitude": where[0], "longitude": where[1], "radius_meters": 150,
            "kind": kind, "notify": False}  # fmt: skip
    assert client.post("/api/places", json=body).status_code == 201


def test_places_then_people_fill_in_past_days_and_send_nothing(tmp_db, client):
    _history_only(tmp_db)
    _place(client, "Home", HOME, "home")
    _place(client, "School", SCHOOL, "school")
    with patch("findplus.alerts.channels.telegram.send") as send:
        members = [{"device_id": d} for d in SAM]
        sam = {"action": "create", "name": "Sam", "kind": "person", "members": members}
        body = {"accept": [sam], "dismiss": []}
        assert client.post("/api/people/suggestions/accept", json=body).status_code == 200
    assert send.call_count == 0
    status = client.get("/api/people/replay").json()
    assert status["state"] == "done" and status["done"] == status["total"] > 0
    pid = client.get("/api/people").json()[0]["id"]
    day = client.get(f"/api/people/{pid}/day", params={"date": "2026-09-21"}).json()
    texts = [line["text"] for line in day["lines"]]
    assert any("left Home" in t for t in texts), texts
    assert any("arrived at School" in t for t in texts), texts
    with session_scope() as s:
        pending = s.query(GroupPlaceEvent).filter(GroupPlaceEvent.notified_at.is_(None))
        assert pending.count() == 0


def test_nothing_runs_without_people(tmp_db):
    _history_only(tmp_db)
    with patch.object(replay, "_run") as run:
        replay.request("place")
    run.assert_not_called()


def test_the_upgrade_replay_is_queued_once(tmp_db):
    _history_only(tmp_db)
    with session_scope() as s:
        seed_person(s, "Sam", SAM)
        from ._helpers import seed_places

        seed_places(s)
    with patch.object(replay, "request") as req:
        replay.on_start()
        replay.on_start()
    assert req.call_count == 1


def test_a_real_request_runs_on_its_own_thread(tmp_db, monkeypatch):
    from ._helpers import seed_places

    monkeypatch.delenv(replay.SYNC_ENV)
    _history_only(tmp_db)
    with session_scope() as s:
        seed_places(s)
        seed_person(s, "Sam", SAM)
    first = replay.request("place")
    assert first["state"] == "running" and first["reason"] == "place"
    replay.wait(60)
    assert replay.status()["state"] == "done"

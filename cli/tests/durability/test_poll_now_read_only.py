"""POST /api/poll-now must not fetch fixes it cannot save."""

from __future__ import annotations

from findplus.db import integrity


def test_poll_now_is_refused_in_read_only_mode(client, monkeypatch) -> None:
    called = []
    monkeypatch.setattr("findplus.poller.poll_once", lambda **k: called.append(1))
    monkeypatch.setattr(integrity, "_HEALTH", integrity.DbHealth(False, ("page 50 is damaged",)))
    res = client.post("/api/poll-now")
    assert res.status_code == 409
    assert "read-only" in res.json()["detail"] and "restore" in res.json()["detail"].lower()
    assert not called

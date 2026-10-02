"""updater/check.py + scheduler.py: find, download, verify, and stay quiet when off."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.updater import store
from findplus.updater.check import check
from findplus.updater.scheduler import UpdateScheduler, is_due
from findplus.updater.status import status

DMG = b"pretend this is a disk image" * 100


def test_a_newer_release_is_downloaded_and_verified(github, installed, state_dir) -> None:
    name = github.publish("1.3.0", DMG)
    state = check(state_dir, download=True)
    assert state["error"] is None and state["available"] is True
    staged = store.updates_dir(state_dir) / name
    assert staged.read_bytes() == DMG
    assert oct(staged.stat().st_mode & 0o777) == "0o600"
    assert oct(store.updates_dir(state_dir).stat().st_mode & 0o777) == "0o700"
    assert status(state_dir, auto=True)["staged_version"] == "1.3.0"


def test_a_checksum_mismatch_installs_nothing_and_leaves_no_file(github, installed, state_dir):
    github.publish("1.3.0", DMG, sha="0" * 64)
    state = check(state_dir, download=True)
    assert "did not match its published checksum" in state["error"]
    assert "staged" not in state
    assert list(store.updates_dir(state_dir).glob("*.dmg*")) == []


def test_the_same_or_an_older_release_stages_nothing(github, installed, state_dir) -> None:
    github.publish("1.2.1", DMG)
    state = check(state_dir, download=True)
    assert state["available"] is False and "staged" not in state
    assert [h for h in github.hits if h.endswith(".dmg")] == []


def test_outside_the_app_it_only_reports(github, installed, state_dir) -> None:
    github.publish("1.3.0", DMG)
    state = check(state_dir, download=False)
    assert state["available"] is True and "staged" not in state
    assert [h for h in github.hits if "/dl/" in h] == []


def test_a_failed_check_never_raises(installed, state_dir, monkeypatch) -> None:
    monkeypatch.setenv("FINDPLUS_UPDATE_API", "http://127.0.0.1:9")
    state = check(state_dir, download=True)
    assert state["error"].startswith("Could not reach GitHub")


def test_auto_off_makes_no_request(github, installed, state_dir, session) -> None:
    from findplus.updater import prefs

    prefs.set_auto(session, False)
    session.commit()
    github.publish("1.3.0", DMG)
    assert UpdateScheduler(state_dir).tick(first=True) == "off"
    assert github.hits == []


def test_auto_on_checks_at_start_then_waits_six_hours(github, installed, state_dir, in_app):
    github.publish("1.3.0", DMG)
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    sched = UpdateScheduler(state_dir, clock=lambda: now)
    assert sched.tick(first=True) == "checked"
    assert status(state_dir, auto=True)["auto_install_ready"] is True
    hits = len(github.hits)
    assert sched.tick() == "idle" and len(github.hits) == hits


def test_due_rules() -> None:
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    assert is_due(None, now, first=False)
    assert not is_due((now - timedelta(minutes=30)).isoformat(), now, first=True)
    assert is_due((now - timedelta(hours=2)).isoformat(), now, first=True)
    assert not is_due((now - timedelta(hours=2)).isoformat(), now, first=False)
    assert is_due((now - timedelta(hours=6)).isoformat(), now, first=False)
    assert is_due((now + timedelta(days=1)).isoformat(), now, first=False)  # clock moved back


def test_after_the_update_the_old_download_is_removed(github, installed, state_dir) -> None:
    from findplus.updater.status import tidy

    github.publish("1.3.0", DMG)
    check(state_dir, download=True)
    installed("1.3.0")
    tidy(state_dir)
    assert list(store.updates_dir(state_dir).glob("*.dmg")) == []
    assert "staged" not in store.load(state_dir)

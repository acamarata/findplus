"""updater/apply.py + routes_update.py: back up first, verify again, shell only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.updater import store
from findplus.updater.apply import prepare
from findplus.updater.check import check
from findplus.updater.release import UpdateError
from findplus.updater.status import status

DMG = b"disk image bytes" * 64
SHELL = {"X-FindPlus-Client": "updater"}


@pytest.fixture
def staged(github, installed, state_dir, in_app):
    github.publish("1.3.0", DMG)
    check(state_dir, download=True)
    return state_dir


def _settings():
    from findplus.config import get_settings

    return get_settings()


def test_a_verified_backup_is_taken_before_anything_is_handed_over(staged) -> None:
    from findplus.db.backup import list_backups

    s = _settings()
    out = prepare(staged, s.database_path, s.effective_backup_dir)
    backups = list_backups(s.effective_backup_dir)
    assert [b.kind for b in backups] == ["preupdate"]
    assert out["backup"] == str(backups[0].path)
    assert out["kind"] == "dmg" and out["version"] == "1.3.0"
    assert out["result_file"].endswith("updates/last-result")
    assert store.load(staged)["attempt"]["version"] == "1.3.0"
    assert s.database_path.exists()  # the live database stays where it is


def test_a_download_changed_on_disk_is_refused_without_a_backup(staged) -> None:
    from findplus.db.backup import list_backups

    s = _settings()
    path = next(store.updates_dir(staged).glob("*.dmg"))
    path.write_bytes(b"tampered")
    with pytest.raises(UpdateError, match="changed on disk"):
        prepare(staged, s.database_path, s.effective_backup_dir)
    assert list_backups(s.effective_backup_dir) == []


def test_a_failed_backup_installs_nothing(staged, monkeypatch) -> None:
    from findplus.db import backup
    from findplus.updater import apply

    def boom(*_a, **_k):
        raise backup.BackupError("disk full")

    monkeypatch.setattr(apply, "create_backup", boom)
    s = _settings()
    with pytest.raises(UpdateError, match="could not back up its database first"):
        prepare(staged, s.database_path, s.effective_backup_dir)
    assert "attempt" not in store.load(staged)


def test_a_failed_attempt_blocks_automatic_retries_of_that_build(staged) -> None:
    from findplus.updater.status import result_path

    s = _settings()
    prepare(staged, s.database_path, s.effective_backup_dir)
    result_path(staged).write_text("failed the new app is signed by team X\n")
    body = status(staged, auto=True)
    assert body["last_attempt_failed"] is True and body["auto_install_ready"] is False
    assert body["staged_version"] == "1.3.0"  # Update now can still try again


def _client():
    from findplus.api import create_app

    return TestClient(
        create_app(bound_host="127.0.0.1", bound_port=8647), base_url="http://127.0.0.1:8647"
    )


def test_apply_answers_only_the_desktop_shell(staged) -> None:
    client = _client()
    assert client.post("/api/update/apply").status_code == 403
    resp = client.post("/api/update/apply", headers=SHELL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == "1.3.0"


def test_apply_with_nothing_staged_is_a_plain_409(tmp_db, installed) -> None:
    resp = _client().post("/api/update/apply", headers=SHELL)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "There is no update ready to install."


def test_status_and_apply_work_while_locked_but_check_does_not(locked_client, staged) -> None:
    body = locked_client.get("/api/update/status").json()
    assert body["staged_version"] == "1.3.0"
    assert "path" not in str(body).lower().replace("release_url", "")
    assert locked_client.post("/api/update/apply", headers=SHELL).status_code == 200
    assert locked_client.post("/api/update/check").status_code == 401


def test_the_switch_and_dev_folder_round_trip_through_settings(client, tmp_path) -> None:
    body = client.get("/api/settings").json()
    assert body["updates.auto"] is True and body["updates.dev_dir"] is None
    body = client.patch("/api/settings", json={"updates.auto": False}).json()
    assert body["updates.auto"] is False
    body = client.patch("/api/settings", json={"updates.dev_dir": str(tmp_path)}).json()
    assert body["updates.dev_dir"] == str(tmp_path)
    assert client.patch("/api/settings", json={"updates.dev_dir": "relative"}).status_code == 422
    assert client.patch("/api/settings", json={"updates.auto": "yes"}).status_code == 422

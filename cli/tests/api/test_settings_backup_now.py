"""GET /api/settings/backup and POST /api/settings/backup/now (the Settings dialog's backup line)."""

from __future__ import annotations

from findplus.config import get_settings


def test_status_before_any_backup_is_empty(client) -> None:
    body = client.get("/api/settings/backup").json()
    assert body["count"] == 0 and body["last_backup_at"] is None and body["last_kind"] is None
    assert body["directory"].endswith("backups")


def test_back_up_now_takes_a_manual_backup_and_reports_it(client) -> None:
    res = client.post("/api/settings/backup/now")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 1 and body["last_kind"] == "manual"
    assert body["last_backup_at"] and body["last_size_bytes"] > 0
    assert client.get("/api/settings/backup").json()["last_backup_at"] == body["last_backup_at"]
    files = list(get_settings().effective_backup_dir.glob("findplus-manual-*.sqlite"))
    assert len(files) == 1


def test_a_missing_database_says_so_in_plain_words(client, monkeypatch) -> None:
    from findplus.db import backup

    def boom(*args, **kwargs):
        raise backup.BackupError("There is no database to back up yet.")

    monkeypatch.setattr("findplus.api._settings_backup_routes.create_backup", boom)
    res = client.post("/api/settings/backup/now")
    assert res.status_code == 500 and "no database to back up" in res.json()["detail"]

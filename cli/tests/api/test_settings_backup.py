"""Backup settings through GET/PATCH /api/settings and `findplus config`."""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.config import get_settings


def test_get_settings_lists_the_backup_keys_with_defaults(client) -> None:
    body = client.get("/api/settings").json()
    assert body["backup.keep_daily"] == 7 and body["backup.keep_weekly"] == 4
    assert body["backup.directory"].endswith("backups")


def test_patch_changes_and_persists_the_keys(client, tmp_path) -> None:
    target = str(tmp_path / "elsewhere")
    res = client.patch(
        "/api/settings",
        json={"backup.directory": target, "backup.keep_daily": 10, "backup.keep_weekly": 0},
    )
    assert res.status_code == 200
    assert res.json()["backup.directory"] == target
    assert res.json()["backup.keep_daily"] == 10 and res.json()["backup.keep_weekly"] == 0
    settings = get_settings()
    assert settings.effective_backup_dir == tmp_path / "elsewhere" / "findplus-backups"
    assert settings.backup_keep_daily == 10


def test_null_directory_goes_back_to_the_default(client, tmp_path) -> None:
    client.patch("/api/settings", json={"backup.directory": str(tmp_path / "x")})
    res = client.patch("/api/settings", json={"backup.directory": None})
    assert res.json()["backup.directory"].endswith("backups")


def test_bad_values_are_422_and_change_nothing(client) -> None:
    for body in (
        {"backup.keep_daily": 0},
        {"backup.keep_daily": 61},
        {"backup.keep_weekly": 53},
        {"backup.directory": "relative/path"},
        {"backup.keep_daily": None},
    ):
        assert client.patch("/api/settings", json=body).status_code == 422, body
    mixed = client.patch("/api/settings", json={"backup.keep_daily": 9, "backup.keep_weekly": 99})
    assert mixed.status_code == 422
    assert client.get("/api/settings").json()["backup.keep_daily"] == 7


def test_the_cli_validates_the_same_way(client) -> None:
    runner = CliRunner()
    assert runner.invoke(main, ["config", "set", "backup_keep_daily", "0"]).exit_code != 0
    assert runner.invoke(main, ["config", "set", "backup_dir", "nope"]).exit_code != 0
    assert runner.invoke(main, ["config", "set", "backup_keep_daily", "12"]).exit_code == 0
    assert client.get("/api/settings").json()["backup.keep_daily"] == 12

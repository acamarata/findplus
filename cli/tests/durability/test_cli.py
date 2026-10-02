"""The CLI face of backups, restore, check, recompute-quality, export and import."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.config import get_settings
from findplus.db.session import session_scope
from tests.durability._seed import seed_everything


@pytest.fixture
def seeded(tmp_db):
    with session_scope() as s:
        seed_everything(s)
    return tmp_db


def _run(*args: str):
    return CliRunner().invoke(main, list(args), catch_exceptions=False)


def test_backup_then_list(seeded) -> None:
    res = _run("db", "backup")
    assert res.exit_code == 0 and "Backup saved:" in res.output
    listing = _run("db", "backups", "--json")
    rows = json.loads(listing.output)
    assert len(rows) == 1 and rows[0]["kind"] == "manual"
    assert "manual" in _run("db", "backups").output


def test_backups_with_none_says_so(tmp_db) -> None:
    assert "No backups yet" in _run("db", "backups").output


def test_backup_json_and_missing_database(seeded) -> None:
    body = json.loads(_run("db", "backup", "--json").output)
    assert Path(body["path"]).exists() and body["size_bytes"] > 0


def test_check_passes_and_fails_with_a_plain_message(seeded, tmp_path) -> None:
    assert "sound" in _run("db", "check").output
    assert json.loads(_run("db", "check", "--json").output)["ok"] is True
    from findplus.db.session import get_engine

    path = get_settings().database_path
    get_engine().dispose()
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    path.write_bytes(b"garbage" * 1000)
    res = _run("db", "check")
    assert res.exit_code == 1 and "findplus db restore" in res.output


def test_restore_via_the_cli(seeded, monkeypatch) -> None:
    backup_path = json.loads(_run("db", "backup", "--json").output)["path"]
    with session_scope() as s:
        from findplus.db.models import LocationObservation

        s.query(LocationObservation).delete()
    res = _run("db", "restore", backup_path)
    assert res.exit_code == 0 and "Restored from" in res.output and "kept as" in res.output
    with session_scope() as s:
        assert s.query(LocationObservation).count() == 12


def test_restore_refuses_while_running(seeded, monkeypatch) -> None:
    backup_path = json.loads(_run("db", "backup", "--json").output)["path"]
    monkeypatch.setattr("findplus.cli.cmd_serve._check_exclusive", lambda d: (True, "http://x/"))
    res = CliRunner().invoke(main, ["db", "restore", backup_path])
    assert res.exit_code != 0 and "is running" in res.output
    assert CliRunner().invoke(main, ["db", "restore", backup_path, "--force"]).exit_code == 0


def test_restore_rejects_a_junk_file(tmp_db, tmp_path) -> None:
    junk = tmp_path / "j.sqlite"
    junk.write_bytes(b"nope" * 100)
    res = CliRunner().invoke(main, ["db", "restore", str(junk)])
    assert res.exit_code != 0 and "not a SQLite" in res.output


def test_recompute_quality_reports_counts(seeded) -> None:
    res = _run("db", "recompute-quality")
    assert "Scored 12 sighting(s) across" in res.output
    assert "Scored" in _run("db", "recompute-quality", "--since", "2026-09-01").output


def test_export_jsonl_to_a_file_is_private_and_importable(seeded, tmp_path, monkeypatch) -> None:
    out = tmp_path / "all.jsonl"
    res = _run("export", "--format", "jsonl", "-o", str(out))
    assert "Wrote" in res.output
    if os.name != "nt":
        assert stat.S_IMODE(out.stat().st_mode) == 0o600
    first = json.loads(out.read_text().splitlines()[0])
    assert first["t"] == "header" and first["counts"]["observation"] == 12
    # Import into a fresh state directory.
    from findplus.config import reset_settings_cache
    from findplus.db.session import get_engine

    fresh = tmp_path / "fresh"
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(fresh))
    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(fresh / "f.sqlite"))
    reset_settings_cache()
    get_engine.cache_clear()
    res = _run("import", str(out))
    assert "Imported:" in res.output and "12 observation" in res.output
    again = CliRunner().invoke(main, ["import", str(out)])
    assert again.exit_code != 0 and "already has data" in again.output


def test_export_jsonl_to_stdout_and_with_a_range_refused(seeded) -> None:
    res = _run("export", "--format", "jsonl")
    assert res.output.splitlines()[0].startswith('{"t": "header"')
    bad = CliRunner().invoke(main, ["export", "--format", "jsonl", "--day", "2026-09-18"])
    assert bad.exit_code != 0 and "exports everything" in bad.output


def test_db_import_alias_lives_under_db(seeded, tmp_path) -> None:
    out = tmp_path / "x.jsonl"
    _run("export", "--format", "jsonl", "-o", str(out))
    res = CliRunner().invoke(main, ["db", "import", str(out)])
    assert res.exit_code != 0 and "already has data" in res.output

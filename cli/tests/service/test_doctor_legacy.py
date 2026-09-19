"""`findplus doctor`: legacy pre-rename database detection.

Split out of test_doctor.py (PRI rule 7, <=300 lines/file).
Constraints: Every check runs against tmp_path, never the real ~/.findplus.
"""

from __future__ import annotations

from findplus.cli import doctor as doctor_module
from findplus.cli.doctor import check_legacy_database


# ------------------------------------------------------------------------- n
def test_check_legacy_database_passes_when_nothing_is_there(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(doctor_module, "legacy_database_paths", lambda: [tmp_path / "gone.sqlite"])
    c = check_legacy_database(tmp_path / "current.sqlite")
    assert c.passed is True
    assert c.detail == "none found"


def test_check_legacy_database_reports_a_pre_rename_file(tmp_path, monkeypatch) -> None:
    """A user upgrading from bike-tracker must be told their history is there,
    and told how to keep it — Find+ never migrates it silently."""
    old = tmp_path / "data" / "bike-tracker.sqlite"
    old.parent.mkdir()
    old.write_bytes(b"SQLite format 3\x00")
    current = tmp_path / "state" / "findplus.sqlite"
    monkeypatch.setattr(doctor_module, "legacy_database_paths", lambda: [old])

    c = check_legacy_database(current)

    assert c.passed is False
    assert c.repairable is False
    assert str(old) in c.detail
    assert "FINDPLUS_DATABASE_PATH" in c.detail
    assert "Nothing is moved for you." in c.detail


def test_check_legacy_database_ignores_the_database_in_use(tmp_path, monkeypatch) -> None:
    """The old default path is a legitimate current path when it is the one
    FINDPLUS_DATABASE_PATH points at; that must not be reported as a find."""
    db = tmp_path / "data" / "findplus.sqlite"
    db.parent.mkdir()
    db.write_bytes(b"SQLite format 3\x00")
    monkeypatch.setattr(doctor_module, "legacy_database_paths", lambda: [db])

    assert check_legacy_database(db).passed is True


def test_legacy_database_paths_cover_both_old_names(monkeypatch) -> None:
    names = {p.name for p in doctor_module.legacy_database_paths()}
    assert {"findplus.sqlite", "bike-tracker.sqlite"} <= names

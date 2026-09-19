"""`findplus groups` — list, add, remove, members, presence."""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.db.session import session_scope
from findplus.ingest import upsert_device


def _added_id(output: str) -> str:
    # "Created group 1: Family" -> "1"
    return output.split("Created group ", 1)[1].split(":", 1)[0]


def test_groups_list_empty(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["groups", "list"])
    assert result.exit_code == 0


def test_groups_add_creates(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["groups", "add", "Family"])
    assert result.exit_code == 0
    list_result = CliRunner().invoke(main, ["groups", "list"])
    assert "Family" in list_result.output


def test_groups_remove_yes(tmp_db: str) -> None:
    runner = CliRunner()
    add_result = runner.invoke(main, ["groups", "add", "Temp"])
    group_id = _added_id(add_result.output)
    result = runner.invoke(main, ["groups", "remove", group_id, "--yes"])
    assert result.exit_code == 0
    assert "Removed." in result.output


def test_groups_members_set(tmp_db: str) -> None:
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    runner = CliRunner()
    add_result = runner.invoke(main, ["groups", "add", "Family"])
    group_id = _added_id(add_result.output)
    result = runner.invoke(main, ["groups", "members", group_id, "--set", "dev1"])
    assert result.exit_code == 0


def test_groups_presence_shows_verdict(tmp_db: str) -> None:
    runner = CliRunner()
    add_result = runner.invoke(main, ["groups", "add", "Family"])
    group_id = _added_id(add_result.output)
    result = runner.invoke(main, ["groups", "presence", group_id])
    assert result.exit_code == 0
    assert "Verdict:" in result.output

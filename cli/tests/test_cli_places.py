"""`findplus places` — list, add, edit, remove, events."""

from __future__ import annotations

import json

from click.testing import CliRunner

from findplus.cli.main import main


def test_list_empty(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["places", "list"])
    assert result.exit_code == 0
    assert "NAME" in result.output


def test_list_json_empty(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["places", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_add(tmp_db: str) -> None:
    result = CliRunner().invoke(
        main, ["places", "add", "Home", "--lat", "41.1", "--lon", "-80.64", "--radius", "100"]
    )
    assert result.exit_code == 0
    assert "Created place" in result.output


def test_add_invalid_radius(tmp_db: str) -> None:
    result = CliRunner().invoke(
        main, ["places", "add", "Home", "--lat", "41.1", "--lon", "-80.64", "--radius", "10"]
    )
    assert result.exit_code == 1
    assert "Error" in result.output


def _added_id(output: str) -> str:
    # "Created place 1: Home" -> "1"
    return output.split("Created place ", 1)[1].split(":", 1)[0]


def test_edit(tmp_db: str) -> None:
    runner = CliRunner()
    add_result = runner.invoke(
        main, ["places", "add", "Home", "--lat", "41.1", "--lon", "-80.64", "--radius", "100"]
    )
    place_id = _added_id(add_result.output)
    result = runner.invoke(main, ["places", "edit", place_id, "--radius", "200"])
    assert result.exit_code == 0


def test_remove_no_yes(tmp_db: str) -> None:
    runner = CliRunner()
    add_result = runner.invoke(
        main, ["places", "add", "Home", "--lat", "41.1", "--lon", "-80.64", "--radius", "100"]
    )
    place_id = _added_id(add_result.output)
    result = runner.invoke(main, ["places", "remove", place_id])
    assert result.exit_code == 1


def test_remove(tmp_db: str) -> None:
    runner = CliRunner()
    add_result = runner.invoke(
        main, ["places", "add", "Home", "--lat", "41.1", "--lon", "-80.64", "--radius", "100"]
    )
    place_id = _added_id(add_result.output)
    result = runner.invoke(main, ["places", "remove", place_id, "--yes"])
    assert result.exit_code == 0
    list_result = runner.invoke(main, ["places", "list", "--json"])
    assert json.loads(list_result.output) == []


def test_events_empty(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["places", "events"])
    assert result.exit_code == 0

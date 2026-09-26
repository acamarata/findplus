"""`findplus alerts rules edit` — P2 gap audit P18.

Purpose    : The dashboard could edit a rule but the CLI could only add or
             remove one. `edit` calls the same `put_rule`/`RuleUpdate` the
             dialog's PUT request reaches (api/routes_alerts_rules.py), so
             this file exercises the CLI wiring, not the update logic itself
             (test_routes_alerts_rules.py already covers that).
Inputs     : CliRunner invocations against a tmp_db-backed rule.
Outputs    : pytest assertions on exit codes, stdout and the stored row.
Constraints: Only fields actually passed change (exclude_unset semantics);
             the rule's target (--group/--device-id) is not editable here,
             matching the dialog (routes_alerts_rules.py's RuleUpdate has no
             such field).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.db.session import session_scope
from findplus.ingest import upsert_device
from findplus.places.repo import create_place


def _add_rule(runner: CliRunner, **extra: str) -> int:
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    args = ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "native"]
    for k, v in extra.items():
        args += [k, v]
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    return int(result.output.split("Created rule ", 1)[1].split(":", 1)[0])


def _list_json(runner: CliRunner) -> list[dict]:
    return json.loads(runner.invoke(main, ["alerts", "rules", "list", "--json"]).output)


def test_edit_requires_at_least_one_field(tmp_db: str) -> None:
    runner = CliRunner()
    rule_id = _add_rule(runner)
    result = runner.invoke(main, ["alerts", "rules", "edit", str(rule_id)])
    assert result.exit_code != 0
    assert "Provide at least one field" in result.output


def test_edit_unknown_id(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "rules", "edit", "999", "--name", "x"])
    assert result.exit_code != 0
    assert "rule not found" in result.output


def test_edit_renames_and_only_changes_passed_fields(tmp_db: str) -> None:
    runner = CliRunner()
    rule_id = _add_rule(runner)
    result = runner.invoke(main, ["alerts", "rules", "edit", str(rule_id), "--name", "renamed"])
    assert result.exit_code == 0, result.output
    assert f"Updated rule {rule_id}: renamed" in result.output
    row = _list_json(runner)[0]
    assert row["name"] == "renamed"
    assert row["cooldown_minutes"] == 30  # untouched
    assert row["channels"] == "native"  # untouched


def test_edit_enter_exit_cooldown_and_disable(tmp_db: str) -> None:
    runner = CliRunner()
    rule_id = _add_rule(runner)
    result = runner.invoke(
        main,
        [
            "alerts",
            "rules",
            "edit",
            str(rule_id),
            "--no-enter",
            "--no-exit",
            "--cooldown",
            "5",
            "--disable",
        ],
    )
    assert result.exit_code == 0, result.output
    row = _list_json(runner)[0]
    assert row["on_enter"] is False
    assert row["on_exit"] is False
    assert row["cooldown_minutes"] == 5
    assert row["enabled"] is False


def test_edit_replaces_the_whole_channel_set(tmp_db: str) -> None:
    runner = CliRunner()
    rule_id = _add_rule(runner)
    result = runner.invoke(
        main,
        ["alerts", "rules", "edit", str(rule_id), "--channel", "native"],
    )
    assert result.exit_code == 0, result.output
    assert _list_json(runner)[0]["channels"] == "native"


def test_edit_rejects_an_unconnected_channel(tmp_db: str) -> None:
    """Mirrors UAT2 U11's server-side check that put_rule already enforces."""
    runner = CliRunner()
    rule_id = _add_rule(runner)
    result = runner.invoke(main, ["alerts", "rules", "edit", str(rule_id), "--channel", "telegram"])
    assert result.exit_code != 0
    assert "connected" in result.output


def test_edit_changes_the_place(tmp_db: str) -> None:
    runner = CliRunner()
    rule_id = _add_rule(runner)
    with session_scope() as s:
        place = create_place(
            s,
            name="Home",
            latitude_e7=411000000,
            longitude_e7=-801000000,
            radius_meters=200,
            enter_confirmations=1,
            exit_confirmations=1,
        )
        place_id = place.id
    result = runner.invoke(
        main, ["alerts", "rules", "edit", str(rule_id), "--place", str(place_id)]
    )
    assert result.exit_code == 0, result.output
    assert _list_json(runner)[0]["place_name"] == "Home"


def test_edit_has_no_group_or_device_option(tmp_db: str) -> None:
    """RuleUpdate has no device_id/group_id field; retarget by re-adding."""
    runner = CliRunner()
    rule_id = _add_rule(runner)
    result = runner.invoke(main, ["alerts", "rules", "edit", str(rule_id), "--group", "1"])
    assert result.exit_code != 0
    assert "no such option" in result.output.lower()

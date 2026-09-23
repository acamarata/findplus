"""`findplus alerts deliveries`/`rules list` render local time and yes/no.

Purpose : UAT3 N25 -- `alerts deliveries` printed SENT_AT/NEXT_ATTEMPT as raw
          UTC ISO and `alerts rules list` printed ENABLED as Python's
          True/False. Both now go through cli/_fmt.py's `_local_short_time`
          and `_yes_no`, split into their own file rather than growing
          test_cli_alerts.py past the PRI rule-7 file cap (T1, findings queue).
Constraints: `_local_short_time` shares dispatch_core.local_zone() with
          render_message(), so `pinned_tz` (cli/tests/conftest.py) pins it
          the same way the alert-message tests do.
"""

from __future__ import annotations

from datetime import UTC, datetime

from click.testing import CliRunner

from findplus.cli.main import main


def test_deliveries_table_shows_local_short_time_not_raw_utc_iso(tmp_db: str, pinned_tz) -> None:
    from findplus.db.models_alerts import AlertDelivery
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    pinned_tz("America/New_York")
    runner = CliRunner()
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    add_result = runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )
    rule_id = int(add_result.output.split("Created rule ", 1)[1].split(":", 1)[0])
    with session_scope() as s:
        s.add(
            AlertDelivery(
                rule_id=rule_id,
                event_kind="device",
                event_id=1,
                sent_at=datetime(2026, 9, 23, 6, 30, 39, tzinfo=UTC),
                status="retrying",
                next_attempt_at=datetime(2026, 9, 23, 7, 0, 0, tzinfo=UTC),
                channel="telegram",
            )
        )

    result = runner.invoke(main, ["alerts", "deliveries"])

    assert result.exit_code == 0, result.output
    assert "2026-09-23T06:30:39+00:00" not in result.output
    assert "2026-09-23T07:00:00+00:00" not in result.output
    # September in America/New_York is EDT (UTC-4): 06:30 -> 02:30, 07:00 -> 03:00.
    assert "2026-09-23 02:30 EDT" in result.output
    assert "2026-09-23 03:00 EDT" in result.output


def test_deliveries_table_leaves_an_open_next_attempt_blank(tmp_db: str, pinned_tz) -> None:
    from findplus.db.models_alerts import AlertDelivery
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    pinned_tz("America/New_York")
    runner = CliRunner()
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    add_result = runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )
    rule_id = int(add_result.output.split("Created rule ", 1)[1].split(":", 1)[0])
    with session_scope() as s:
        s.add(
            AlertDelivery(
                rule_id=rule_id,
                event_kind="device",
                event_id=1,
                sent_at=datetime(2026, 9, 23, 6, 30, 39, tzinfo=UTC),
                status="sent",
                channel="telegram",
            )
        )

    result = runner.invoke(main, ["alerts", "deliveries"])

    assert result.exit_code == 0, result.output
    assert "telegram" in result.output
    assert "None" not in result.output  # NEXT_ATTEMPT is blank, not the string "None"


def test_rules_list_table_shows_yes_no_not_python_bool(tmp_db: str) -> None:
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    runner = CliRunner()
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )

    result = runner.invoke(main, ["alerts", "rules", "list"])

    assert result.exit_code == 0, result.output
    assert "True" not in result.output
    assert "False" not in result.output
    assert "yes" in result.output


def test_rules_list_json_output_keeps_a_raw_boolean(tmp_db: str) -> None:
    """--json is untouched: a script parsing it must still get a real bool."""
    import json

    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    runner = CliRunner()
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )

    result = runner.invoke(main, ["alerts", "rules", "list", "--json"])

    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert records[0]["enabled"] is True

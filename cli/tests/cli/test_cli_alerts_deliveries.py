"""`findplus alerts deliveries --json` — GP-R5-2.

Purpose : `deliveries --json` had no CLI test. New file rather than growing
          test_cli_alerts.py past the PRI rule-7 <=300-line file cap (the
          same reason alerts_fmt.py's row builders and
          test_cli_alerts_formatting.py were split out).
Constraints: `--json` keeps raw stored ids and UTC ISO-8601 timestamps
          (ruling R-P2-31); only the human table renders local time
          (test_cli_alerts_formatting.py covers that).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from findplus.cli.main import main


def test_deliveries_json_empty_list(tmp_db: str) -> None:
    """GP-R5-2: `alerts deliveries --json` had no CLI test -- the empty case."""
    result = CliRunner().invoke(main, ["alerts", "deliveries", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


def test_deliveries_json_carries_the_delivery_fields_in_utc(tmp_db: str) -> None:
    """GP-R5-2: `--json` keeps raw stored ids and UTC ISO-8601 timestamps,
    unlike the table (test_cli_alerts_formatting.py), which renders local
    time."""
    from datetime import UTC, datetime

    from findplus.db.models_alerts import AlertDelivery
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    runner = CliRunner()
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    add_result = runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )
    rule_id = int(add_result.output.split("Created rule ", 1)[1].split(":", 1)[0])
    sent_at = datetime(2026, 9, 23, 6, 30, 39, tzinfo=UTC)
    with session_scope() as s:
        s.add(
            AlertDelivery(
                rule_id=rule_id,
                event_kind="device",
                event_id=1,
                sent_at=sent_at,
                status="failed",
                error="bot_token is invalid",
                channel="telegram",
                attempts=2,
            )
        )

    result = runner.invoke(main, ["alerts", "deliveries", "--json"])

    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert len(records) == 1
    record = records[0]
    assert record["rule_id"] == rule_id
    assert record["rule_name"] == "r1"
    assert record["channel"] == "telegram"
    assert record["event_kind"] == "device"
    assert record["status"] == "failed"
    assert record["error"] == "bot_token is invalid"
    assert record["attempts"] == 2
    assert record["sent_at"] == "2026-09-23T06:30:39+00:00"
    assert record["delivered_at"] is None
    assert record["next_attempt_at"] is None

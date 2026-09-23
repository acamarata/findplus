"""`findplus alerts rules list` channel display names — GP-R5-3.

Purpose : `rules list` renders channel display names via display_channels()
          (UAT4 N38), but that rendering had no CLI test. New file rather
          than growing test_cli_alerts.py past the PRI rule-7 <=300-line
          file cap.
Constraints: `--json` keeps the raw stored channel ids, unaffected by the
          display-name catalog (channels_field.py's CHANNEL_DISPLAY_NAMES).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from findplus.cli.main import main


def test_rules_list_shows_channel_display_names(tmp_db: str) -> None:
    """GP-R5-3: `alerts rules list` renders channel display names via
    display_channels() (UAT4 N38) -- untested until now. --json keeps the
    raw stored ids, unaffected by the display-name catalog."""
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "r1",
            "--device-id",
            "dev1",
            "--channel",
            "native",
            "--channel",
            "whatsapp",
        ],
    )

    list_result = runner.invoke(main, ["alerts", "rules", "list"])
    assert list_result.exit_code == 0, list_result.output
    assert "Desktop notification" in list_result.output
    assert "WhatsApp" in list_result.output
    assert "native,whatsapp" not in list_result.output

    json_result = runner.invoke(main, ["alerts", "rules", "list", "--json"])
    listed = json.loads(json_result.output)
    assert listed[0]["channels"] == "native,whatsapp"

"""Migration 0008: alert_rules.channels, alert_deliveries.channel/delivered_at.

Purpose : Prove the backfill runs while alert_rules.channel still exists (step
          order is the whole schema risk here, specs/notifications.md § 0), that
          the widened status CHECK and the four-column dedup UNIQUE land, and
          that the downgrade is clean on a populated database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-20T00:00:00"


def _cfg(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    return get_alembic_config(f"sqlite:///{db_path}"), db_path


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _columns(db_path: Path, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(_engine(db_path)).get_columns(table)}


def _seed_rule_and_delivery(conn, channel: str, rule_id: int, event_id: int) -> None:
    """One alert_rules row plus one alert_deliveries row, in the pre-0008 shape."""
    conn.execute(
        sa.text(
            "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, last_seen_at) "
            "VALUES (:id, 'Tag', 0, :now, :now)"
        ),
        {"id": f"dev{rule_id}", "now": NOW},
    )
    conn.execute(
        sa.text(
            "INSERT INTO alert_rules (id, name, device_id, on_enter, on_exit, channel, "
            "cooldown_minutes, enabled, also_notify_members, created_at) "
            "VALUES (:rid, :name, :dev, 1, 1, :ch, 30, 1, 0, :now)"
        ),
        {"rid": rule_id, "name": f"r{rule_id}", "dev": f"dev{rule_id}", "ch": channel, "now": NOW},
    )
    conn.execute(
        sa.text(
            "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, sent_at, status) "
            "VALUES (:rid, 'device', :eid, :now, 'sent')"
        ),
        {"rid": rule_id, "eid": event_id, "now": NOW},
    )


def test_upgrade_moves_channel_to_channels_and_adds_the_delivery_columns(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0008")
    rules = _columns(db_path, "alert_rules")
    assert "channels" in rules
    assert "channel" not in rules
    assert {"channel", "delivered_at"} <= _columns(db_path, "alert_deliveries")


def test_existing_rows_are_backfilled_before_the_source_column_is_dropped(tmp_path: Path) -> None:
    """The step order spec § 0 pins: deliveries copy the rule's channel first."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, "telegram", rule_id=1, event_id=10)
        _seed_rule_and_delivery(conn, "webhook", rule_id=2, event_id=20)
    command.upgrade(cfg, "0008")
    with engine.begin() as conn:
        rules = dict(conn.execute(sa.text("SELECT id, channels FROM alert_rules")).all())
        deliveries = dict(
            conn.execute(sa.text("SELECT rule_id, channel FROM alert_deliveries")).all()
        )
    assert rules == {1: "telegram", 2: "webhook"}
    assert deliveries == {1: "telegram", 2: "webhook"}


def test_status_check_accepts_queued_and_delivered(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, "telegram", rule_id=1, event_id=10)
    command.upgrade(cfg, "0008")
    with engine.begin() as conn:
        for status in ("queued", "delivered"):
            conn.execute(
                sa.text(
                    "INSERT INTO alert_deliveries "
                    "(rule_id, event_kind, event_id, channel, sent_at, status) "
                    "VALUES (1, 'device', :eid, 'native', :now, :st)"
                ),
                {"eid": 100 if status == "queued" else 101, "now": NOW, "st": status},
            )
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO alert_deliveries "
                    "(rule_id, event_kind, event_id, channel, sent_at, status) "
                    "VALUES (1, 'device', 102, 'native', :now, 'bogus')"
                ),
                {"now": NOW},
            )


def test_dedup_unique_now_includes_the_channel(tmp_path: Path) -> None:
    """The same event under two channels is two rows; the same channel twice is not."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, "telegram", rule_id=1, event_id=10)
    command.upgrade(cfg, "0008")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO alert_deliveries "
                "(rule_id, event_kind, event_id, channel, sent_at, status) "
                "VALUES (1, 'device', 10, 'native', :now, 'queued')"
            ),
            {"now": NOW},
        )
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO alert_deliveries "
                "(rule_id, event_kind, event_id, channel, sent_at, status) "
                "VALUES (1, 'device', 10, 'native', :now, 'queued')"
            ),
            {"now": NOW},
        )


def test_downgrade_restores_channel_and_falls_back_for_a_1_1_only_channel(tmp_path: Path) -> None:
    """0007's CHECK only knows telegram/webhook, so native/whatsapp become telegram."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, "telegram", rule_id=1, event_id=10)
    command.upgrade(cfg, "0008")
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE alert_rules SET channels = 'native,telegram' WHERE id = 1"))
    command.downgrade(cfg, "0007")
    assert "channels" not in _columns(db_path, "alert_rules")
    assert "channel" not in _columns(db_path, "alert_deliveries")
    with engine.begin() as conn:
        channel = conn.execute(sa.text("SELECT channel FROM alert_rules WHERE id = 1")).scalar_one()
    assert channel == "telegram"


def test_downgrade_keeps_a_webhook_rule_on_webhook(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, "webhook", rule_id=1, event_id=10)
    command.upgrade(cfg, "0008")
    command.downgrade(cfg, "0007")
    with engine.begin() as conn:
        channel = conn.execute(sa.text("SELECT channel FROM alert_rules WHERE id = 1")).scalar_one()
    assert channel == "webhook"


def test_upgrade_never_cascades_the_delivery_history_away(tmp_path: Path) -> None:
    """alert_deliveries.rule_id is ON DELETE CASCADE and batch mode DROPs alert_rules.

    Without the stash/pragma guard in the revision, every delivery row vanishes on
    upgrade: silent data loss with no error anywhere.
    """
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, "telegram", rule_id=1, event_id=10)
        conn.execute(
            sa.text(
                "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, sent_at, status) "
                "VALUES (1, 'device', 11, :now, 'failed')"
            ),
            {"now": NOW},
        )
    command.upgrade(cfg, "0008")
    with engine.begin() as conn:
        rows = conn.execute(
            sa.text("SELECT event_id, channel, status FROM alert_deliveries ORDER BY event_id")
        ).all()
    assert [tuple(r) for r in rows] == [
        (10, "telegram", "sent"),
        (11, "telegram", "failed"),
    ]


def test_the_stash_table_is_never_left_behind(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0008")
    tables = set(sa.inspect(_engine(db_path)).get_table_names())
    assert not {t for t in tables if t.startswith("_alert_deliveries_0008")}

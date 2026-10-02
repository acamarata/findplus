"""People, presence and observation quality (specs/people-and-presence.md § 1.4)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-01

Schema only; the engines that read and write these columns live in people/
and quality/.

1. Plain column adds, no rebuild: groups.kind ('set' | 'person' | 'pet'),
   devices.role + carry_weight, places.kind (+ kind_guessed, filled from the
   name for existing places), and group_place_events.basis,
   note, lead_device_id. Values are validated in the API layer, not by a
   CHECK, so `groups`, `devices` and `places` (all parents of ON DELETE
   CASCADE children) are never rebuilt.
2. Two batch rebuilds. alert_deliveries' event_kind CHECK gains
   'left_behind'. alert_rules gains all_people and its target CHECK becomes
   "all people, or exactly one of group/device". alert_deliveries.rule_id is
   ON DELETE CASCADE, so rebuilding alert_rules with foreign keys enforced
   would wipe the delivery log. Both runners (migrate.upgrade_to_head and
   env.py) wrap the run in fk_disabled; this revision refuses to rebuild if
   enforcement is somehow still on, and stashes the delivery rows around
   the rebuild exactly as 0008 does.
3. Four new tables: person_place_states, left_behind, observation_quality,
   digest_runs. Every link to a parent is ON DELETE CASCADE (place_id on
   left_behind and corroborated_by on observation_quality are SET NULL).
4. Triggers keep a tracker in at most one person/pet group: on a new
   membership, on a moved membership, and when a set is turned into a person.
   A future batch rebuild of `groups` or `device_group` drops them; the
   migration test checks they exist at head.

downgrade() is lossy, as 0012's is: kinds, roles, weights, the new tables,
all-people rules (with their deliveries) and left-behind deliveries go.
Person events stay in group_place_events as plain group rows.
"""

from __future__ import annotations

import sqlite3

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str = "0012"
branch_labels = None
depends_on = None

_STASH = "_alert_deliveries_0013_stash"
_KIND_OLD = "event_kind IN ('device','group')"
_KIND_NEW = "event_kind IN ('device','group','left_behind')"
_TARGET_OLD = "(group_id IS NULL) <> (device_id IS NULL)"
_TARGET_NEW = (
    "(all_people = 1 AND group_id IS NULL AND device_id IS NULL) OR "
    "(all_people = 0 AND ((group_id IS NULL) <> (device_id IS NULL)))"
)
_PERSONISH = "('person','pet')"
_ABORT = "SELECT RAISE(ABORT, 'one_person_per_device: tracker already belongs to a person')"
_TRIGGERS = {
    "trg_one_person_per_device": f"""
        CREATE TRIGGER trg_one_person_per_device BEFORE INSERT ON device_group
        WHEN (SELECT kind FROM groups WHERE id = NEW.group_id) IN {_PERSONISH}
         AND EXISTS (SELECT 1 FROM device_group dg JOIN groups g ON g.id = dg.group_id
                     WHERE dg.device_id = NEW.device_id AND dg.group_id <> NEW.group_id
                       AND g.kind IN {_PERSONISH})
        BEGIN {_ABORT}; END""",
    "trg_one_person_per_device_move": f"""
        CREATE TRIGGER trg_one_person_per_device_move BEFORE UPDATE ON device_group
        WHEN (SELECT kind FROM groups WHERE id = NEW.group_id) IN {_PERSONISH}
         AND EXISTS (SELECT 1 FROM device_group dg JOIN groups g ON g.id = dg.group_id
                     WHERE dg.device_id = NEW.device_id AND dg.group_id <> NEW.group_id
                       AND NOT (dg.device_id = OLD.device_id AND dg.group_id = OLD.group_id)
                       AND g.kind IN {_PERSONISH})
        BEGIN {_ABORT}; END""",
    "trg_one_person_per_device_kind": f"""
        CREATE TRIGGER trg_one_person_per_device_kind BEFORE UPDATE OF kind ON groups
        WHEN NEW.kind IN {_PERSONISH}
         AND EXISTS (SELECT 1 FROM device_group m
                     JOIN device_group o ON o.device_id = m.device_id AND o.group_id <> m.group_id
                     JOIN groups g ON g.id = o.group_id
                     WHERE m.group_id = NEW.id AND g.kind IN {_PERSONISH})
        BEGIN {_ABORT}; END""",
}


def _require_fk_off() -> None:
    """Refuse to rebuild alert_rules while ON DELETE CASCADE is live."""
    op.execute("PRAGMA foreign_keys=OFF")
    if op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "0013 must run with foreign keys off (use findplus migrate); "
            "rebuilding alert_rules with them on would delete the delivery log"
        )


def _stash_deliveries() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_STASH}")
    op.execute(f"CREATE TABLE {_STASH} AS SELECT * FROM alert_deliveries")


def _restore_deliveries() -> None:
    op.execute("DELETE FROM alert_deliveries")
    op.execute(f"INSERT INTO alert_deliveries SELECT * FROM {_STASH}")
    op.execute(f"DROP TABLE {_STASH}")


def _drop_column(table: str, column: str) -> None:
    """Native DROP COLUMN (no rebuild of a cascade parent) where SQLite has it."""
    if sqlite3.sqlite_version_info >= (3, 35, 0):
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    else:  # pragma: no cover - every supported Python ships a newer SQLite
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)


def _add_plain_columns() -> None:
    op.add_column("groups", sa.Column("kind", sa.String(8), nullable=False, server_default="set"))
    op.add_column("devices", sa.Column("role", sa.String(16), nullable=True))
    op.add_column("devices", sa.Column("carry_weight", sa.Float(), nullable=True))
    op.add_column("places", sa.Column("kind", sa.String(8), nullable=False, server_default="other"))
    op.add_column(
        "places", sa.Column("kind_guessed", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "group_place_events",
        sa.Column("basis", sa.String(8), nullable=False, server_default="quorum"),
    )
    op.add_column("group_place_events", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("group_place_events", sa.Column("lead_device_id", sa.String(128), nullable=True))


def _rebuild_alert_tables() -> None:
    # alert_deliveries first: nothing references it, so its rebuild is safe.
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.alter_column("event_kind", existing_type=sa.String(6), type_=sa.String(16))
        batch.drop_constraint("ck_alert_deliveries_kind", type_="check")
        batch.create_check_constraint("ck_alert_deliveries_kind", _KIND_NEW)
    _stash_deliveries()
    with op.batch_alter_table("alert_rules") as batch:
        batch.add_column(
            sa.Column("all_people", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.drop_constraint("ck_alert_rules_xor_target", type_="check")
        batch.create_check_constraint("ck_alert_rules_target", _TARGET_NEW)
    _restore_deliveries()


def _fk(target: str, ondelete: str = "CASCADE") -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete)


def _create_person_tables() -> None:
    op.create_table(
        "person_place_states",
        sa.Column("group_id", sa.Integer(), _fk("groups.id"), nullable=False),
        sa.Column("place_id", sa.Integer(), _fk("places.id"), nullable=False),
        sa.Column("state", sa.String(8), nullable=False, server_default="unknown"),
        sa.Column("since_observed_at", sa.DateTime(), nullable=True),
        sa.Column("pending_side", sa.String(8), nullable=True),
        sa.Column("pending_since", sa.DateTime(), nullable=True),
        sa.Column("last_transition_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "place_id"),
    )
    op.create_table(
        "left_behind",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), _fk("groups.id"), nullable=False),
        sa.Column("device_id", sa.String(128), _fk("devices.device_id"), nullable=False),
        sa.Column("place_id", sa.Integer(), _fk("places.id", "SET NULL"), nullable=True),
        sa.Column("anchor_lat_e7", sa.Integer(), nullable=False),
        sa.Column("anchor_lon_e7", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("started_observed_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("cleared_at", sa.DateTime(), nullable=True),
        sa.Column("clear_reason", sa.String(16), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_left_behind_group_device_state", "left_behind", ["group_id", "device_id", "state"])


def _create_quality_and_digest_tables() -> None:
    obs = "location_observations.id"
    op.create_table(
        "observation_quality",
        sa.Column("observation_id", sa.Integer(), _fk(obs), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("suspect", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reasons", sa.Text(), nullable=False, server_default=""),
        sa.Column("corroborated_by", sa.Integer(), _fk(obs, "SET NULL"), nullable=True),
        sa.Column("algo_version", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_observation_quality_suspect", "observation_quality", ["suspect"])
    op.create_table(
        "digest_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), _fk("groups.id"), nullable=False),
        sa.Column("local_date", sa.String(10), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("target", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "group_id", "local_date", "channel", "target", name="uq_digest_runs_once"
        ),
    )


def _guess_place_kinds() -> None:
    """Existing places get the kind their name suggests ("Home" -> home), flagged
    kind_guessed so the places list asks the owner to confirm it. Without this
    an upgraded Home stays 'other': left-behind alerts on there, no "Overnight
    at Home" (review r116 #8). Same rule as a new place: places/kinds.py."""
    from findplus.places.kinds import guess_place_kind

    conn = op.get_bind()
    for pid, name in conn.execute(sa.text("SELECT id, name FROM places WHERE kind = 'other'")):
        kind = guess_place_kind(name)
        if kind != "other":
            conn.execute(
                sa.text("UPDATE places SET kind = :k, kind_guessed = 1 WHERE id = :i"),
                {"k": kind, "i": pid},
            )


def upgrade() -> None:
    _require_fk_off()
    _add_plain_columns()
    _guess_place_kinds()
    _rebuild_alert_tables()
    _create_person_tables()
    _create_quality_and_digest_tables()
    for sql in _TRIGGERS.values():
        op.execute(sql)


def _narrow_alert_tables() -> None:
    # Rows the old CHECKs reject go first, children before parents, because
    # foreign keys are off and nothing would cascade for us.
    op.execute("DELETE FROM alert_deliveries WHERE event_kind = 'left_behind'")
    op.execute(
        "DELETE FROM alert_deliveries WHERE rule_id IN "
        "(SELECT id FROM alert_rules WHERE all_people = 1)"
    )
    op.execute("DELETE FROM alert_rules WHERE all_people = 1")
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.drop_constraint("ck_alert_deliveries_kind", type_="check")
        batch.create_check_constraint("ck_alert_deliveries_kind", _KIND_OLD)
        batch.alter_column("event_kind", existing_type=sa.String(16), type_=sa.String(6))
    _stash_deliveries()
    with op.batch_alter_table("alert_rules") as batch:
        batch.drop_constraint("ck_alert_rules_target", type_="check")
        batch.create_check_constraint("ck_alert_rules_xor_target", _TARGET_OLD)
        batch.drop_column("all_people")
    _restore_deliveries()


def downgrade() -> None:
    _require_fk_off()
    for name in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("digest_runs")
    op.drop_index("ix_observation_quality_suspect", table_name="observation_quality")
    op.drop_table("observation_quality")
    op.drop_index("ix_left_behind_group_device_state", table_name="left_behind")
    op.drop_table("left_behind")
    op.drop_table("person_place_states")
    _narrow_alert_tables()
    for table, column in (
        ("group_place_events", "lead_device_id"),
        ("group_place_events", "note"),
        ("group_place_events", "basis"),
        ("places", "kind_guessed"),
        ("places", "kind"),
        ("devices", "carry_weight"),
        ("devices", "role"),
        ("groups", "kind"),
    ):
        _drop_column(table, column)

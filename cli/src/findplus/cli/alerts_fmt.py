"""Row/record builders for `alerts rules list` and `alerts deliveries`.

Purpose    : Split out of alerts.py at the PRI rule-7 <=300-line file cap
             (UAT4 N38/N43 pushed it over): the `--json` record shape and the
             plain-table row shape for both commands, kept together since
             they read the same ORM rows and must stay in sync.
Inputs     : The joined ORM rows `alerts.py`'s `_list_rules`/`deliveries_cmd`
             query already build.
Outputs    : `_rule_records`/`_delivery_records` (JSON-ready dicts, raw ids,
             UTC ISO-8601 timestamps) and `_rule_table_rows`/
             `_delivery_table_rows` (display-formatted tuples for
             `_render_table`).
Constraints: No session_scope/DB access here -- pure formatting over rows the
             caller already fetched.
"""

from __future__ import annotations

from findplus.alerts.channels_field import display_channels

from ._fmt import _local_short_time, _yes_no

_RULE_KEYS = (
    "id",
    "name",
    "place_id",
    "place_name",
    "group_id",
    "group_name",
    "device_id",
    "device_name",
    "on_enter",
    "on_exit",
    "channels",
    "cooldown_minutes",
    "enabled",
    "also_notify_members",
)

#: Keys for `alerts deliveries --json` -- same convention as `rules list
#: --json` (UAT4 N43): raw stored ids, UTC ISO-8601 timestamps, no rendering.
_DELIVERY_KEYS = (
    "id",
    "rule_id",
    "rule_name",
    "channel",
    #: '' for every channel with no per-target concept; a telegram row's own
    #: target (chat id/username) otherwise -- migration 0011.
    "target",
    "event_kind",
    "event_id",
    "sent_at",
    "delivered_at",
    "status",
    "error",
    "attempts",
    "next_attempt_at",
)


def _rule_records(rows: list[tuple]) -> list[dict]:
    return [
        dict(
            zip(
                _RULE_KEYS,
                (
                    r.id,
                    r.name,
                    r.place_id,
                    place_name,
                    r.group_id,
                    group_name,
                    r.device_id,
                    device_name,
                    r.on_enter,
                    r.on_exit,
                    r.channels,
                    r.cooldown_minutes,
                    r.enabled,
                    r.also_notify_members,
                ),
                strict=True,
            )
        )
        for r, place_name, group_name, device_name in rows
    ]


def _rule_table_rows(rows: list[tuple]) -> list[tuple]:
    # UAT4 N38: CHANNELS renders display names ("Desktop notification,
    # WhatsApp"), the same catalog the rule dialog and delivery log use --
    # --json keeps the raw stored ids.
    return [
        (
            r.id,
            r.name,
            place_name or "",
            group_name or "",
            device_name or "",
            display_channels(r.channels),
            r.cooldown_minutes,
            _yes_no(r.enabled),
        )
        for r, place_name, group_name, device_name in rows
    ]


def _delivery_records(rows: list[tuple]) -> list[dict]:
    """`--json` rows: raw stored ids, UTC ISO-8601 timestamps, no rendering."""
    return [
        dict(
            zip(
                _DELIVERY_KEYS,
                (
                    d.id,
                    d.rule_id,
                    rule_name,
                    d.channel,
                    d.target,
                    d.event_kind,
                    d.event_id,
                    d.sent_at.isoformat(),
                    d.delivered_at.isoformat() if d.delivered_at else None,
                    d.status,
                    d.error,
                    d.attempts,
                    d.next_attempt_at.isoformat() if d.next_attempt_at else None,
                ),
                strict=True,
            )
        )
        for d, rule_name in rows
    ]


def _delivery_table_rows(rows: list[tuple], error_max: int) -> list[tuple]:
    table_rows = []
    for d, rule_name in rows:
        error = d.error or ""
        if len(error) > error_max:
            error = error[: error_max - 1] + "…"
        table_rows.append(
            (
                d.id,
                rule_name,
                d.channel,
                d.target or "",
                d.event_kind or "",
                _local_short_time(d.sent_at),
                d.status or "",
                d.attempts,
                _local_short_time(d.next_attempt_at),
                error,
            )
        )
    return table_rows

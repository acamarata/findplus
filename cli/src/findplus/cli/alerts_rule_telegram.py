"""`findplus alerts rules add/edit`'s `--telegram-target`/`--telegram-all`
option handling.

Purpose    : Split out of alerts.py at the PRI rule-7 300-line file cap
             (WP10, gap-audit P13, added these two options to both `add` and
             `edit`). `_resolve_telegram_targets_option` turns the raw Click
             values into the value RuleCreate/AlertRule wants (None = every
             saved target); `_rule_edit_fields` is `rules_edit`'s own
             fields-dict builder, pulled out to keep that command under the
             50-line function cap once these two options joined its existing
             seven.
Inputs     : The `--telegram-target`(repeatable)/`--telegram-all` Click
             values, plus rules_edit's other already-parsed option values.
Outputs    : A value for AlertRule.telegram_targets / RuleUpdate, or the
             `fields` dict `rules_edit` passes to `RuleUpdate(**fields)`.
Constraints: No DB/session access here -- pure option-shape helpers, same
             posture as alerts_fmt.py's row builders.
"""

from __future__ import annotations

import click


def _resolve_telegram_targets_option(
    telegram_targets: tuple[str, ...], telegram_all: bool
) -> list[str] | None:
    """`--telegram-target` (repeatable) / `--telegram-all` -> the value to
    store, or None for "every saved target" (`rules_add`'s own default
    without either flag; `rules_edit` only touches the field at all when one
    of these was actually passed -- see `_rule_edit_fields` below)."""
    if telegram_targets and telegram_all:
        raise click.ClickException("Provide --telegram-target or --telegram-all, not both")
    return None if telegram_all or not telegram_targets else list(telegram_targets)


def _rule_edit_fields(
    name: str | None,
    place_id: int | None,
    enter: bool | None,
    exit_: bool | None,
    channels: tuple[str, ...],
    cooldown: int | None,
    enabled: bool | None,
    telegram_targets: tuple[str, ...],
    telegram_all: bool,
) -> dict:
    """The `RuleUpdate(**fields)` kwargs `rules_edit` sends -- only the
    options actually passed, split out to keep `rules_edit` itself under the
    PRI rule-7 50-line cap."""
    fields: dict = {}
    if name is not None:
        fields["name"] = name
    if place_id is not None:
        fields["place_id"] = place_id
    if enter is not None:
        fields["on_enter"] = enter
    if exit_ is not None:
        fields["on_exit"] = exit_
    if channels:
        fields["channels"] = list(channels)
    if cooldown is not None:
        fields["cooldown_minutes"] = cooldown
    if enabled is not None:
        fields["enabled"] = enabled
    if telegram_targets or telegram_all:
        fields["telegram_targets"] = _resolve_telegram_targets_option(
            telegram_targets, telegram_all
        )
    return fields

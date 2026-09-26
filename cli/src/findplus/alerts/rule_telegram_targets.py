"""Per-rule Telegram target subset: stored shape, validation, pruning.

Purpose    : The owner's ask (gap-audit P13/WP10): a Telegram rule used to
             fan out to every saved chat, with no way to send "Kid left
             Home" to one parent only. `alert_rules.telegram_targets`
             (migration 0012) holds an optional subset of the account's
             saved Telegram chat ids; this module is the one place that
             knows its stored shape, validates a proposed subset against
             what is actually saved, and prunes a subset when a saved
             target is removed or the channel is disconnected.
Inputs     : The stored column value (str | None), and `AlertsChannels.
             telegram.chat_ids` from alerts/store.py.
Outputs    : parse/format round-trip the stored string; validate raises
             ValueError (the API layer turns that into a 422); prune updates
             rows in place and commits.
Constraints:
    - NULL means "every saved target" -- the pre-1.1.3 behaviour, and the
      default for a new rule. `""` is a distinct, meaningful value: the
      owner explicitly picked no chat, so dispatch.py skips Telegram for
      that rule rather than falling back to "all" (surprise sends are worse
      than a rule that visibly does nothing for one channel).
    - No sorting: order comes from the saved chat_ids list (and the UI's own
      checkbox order), unlike channels_field.format_channels's normalized
      set -- there is no natural sort for chat ids/labels worth imposing.
"""

from __future__ import annotations

from collections.abc import Iterable


def parse_rule_telegram_targets(stored: str | None) -> list[str] | None:
    """NULL -> None ("every saved target"); `""` -> `[]`; "1,2" -> ["1", "2"]."""
    if stored is None:
        return None
    return [v.strip() for v in stored.split(",") if v.strip()]


def format_rule_telegram_targets(values: list[str] | None) -> str | None:
    """None -> NULL; `[]` -> `""`; de-duplicated, order preserved."""
    if values is None:
        return None
    seen: list[str] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return ",".join(seen)


def validate_rule_telegram_targets(values: list[str] | None) -> list[str] | None:
    """Every id must be one of the account's currently saved Telegram chat
    ids -- a rule can only narrow to a chat that exists, never invent one.

    None ("every target") and `[]` (explicit "none") both skip the saved-set
    check: there is nothing to validate a request for zero or "all" against.
    Used as a pydantic field_validator (routes_alerts_rules.py) and called
    directly by the CLI (cli/alerts.py), so both surfaces reject the same
    unknown id the same way.
    """
    if not values:
        return values
    from findplus.alerts.store import load_alerts

    ch = load_alerts()
    saved = set(ch.telegram.chat_ids) if ch.telegram else set()
    unknown = [v for v in values if v not in saved]
    if unknown:
        raise ValueError(
            "unknown Telegram target(s): " + ", ".join(unknown) + " -- save them as targets first"
        )
    return values


def prune_rule_telegram_targets(session, saved_ids: Iterable[str]) -> int:
    """Drop any id from every rule's explicit subset that is no longer among
    the account's saved Telegram targets -- a target removed from Settings
    or the dashboard, or the whole channel disconnected (`saved_ids` empty
    then). A rule with `telegram_targets` NULL ("every target") is never
    touched: there is nothing explicit to prune. Returns how many rules
    changed, for the caller's own tests (routes_alerts_telegram.py calls
    this after every save_channel(telegram=...) that can shrink chat_ids).
    """
    from findplus.db.models_alerts import AlertRule

    saved = set(saved_ids)
    changed = 0
    rows = session.query(AlertRule).filter(AlertRule.telegram_targets.isnot(None)).all()
    for rule in rows:
        current = parse_rule_telegram_targets(rule.telegram_targets)
        kept = [t for t in current if t in saved]
        new_value = format_rule_telegram_targets(kept)
        if new_value != rule.telegram_targets:
            rule.telegram_targets = new_value
            changed += 1
    if changed:
        session.commit()
    return changed

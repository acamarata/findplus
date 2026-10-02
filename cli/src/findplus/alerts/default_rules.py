"""The default "arrivals and departures for everyone" rule per place (spec § 5.3).

Purpose : Every new place notifies arrive and leave for every person, on the
          channel the owner actually uses, with no extra setup. Existing places
          get the same rule from a one-click backfill ("Notify me") that shows
          what it would add first.
Inputs  : A session, a Place (or every place), the configured channels.
Outputs : Unsaved/saved AlertRule rows and their preview dicts.
Constraints: Channel choice: exactly one of telegram/whatsapp/webhook ->
          that one; several -> telegram if present, else all of them; none ->
          native when the desktop app has shown a notification, else the rule
          is saved DISABLED with the hint "Connect Telegram to get these."
          Cooldown 0: the person engine debounces, and a cooldown keyed on
          (rule, channel, place) would swallow "left" 20 minutes after "arrived".
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.alerts.channels_field import format_channels, parse_channels
from findplus.db.models import Place
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.people.messages import t

_EXTERNAL = ("telegram", "whatsapp", "webhook")


def native_registered(session: Session) -> bool:
    """The desktop app has shown at least one native notification (acked a row)."""
    stmt = select(AlertDelivery.id).where(
        AlertDelivery.channel == "native", AlertDelivery.delivered_at.is_not(None)
    )
    return session.scalar(stmt.limit(1)) is not None


def choose_channels(
    session: Session, channels_cfg=None, wanted: list[str] | None = None
) -> tuple[list[str], bool, str | None]:
    """(channels, enabled, hint) for a new default rule.

    `wanted` is the owner's own pick (the place dialog's channel select): every entry must
    be a connected external channel, else ValueError (the API answers 422).
    """
    if channels_cfg is None:
        from findplus.alerts.store import load_alerts

        channels_cfg = load_alerts()
    configured = [c for c in _EXTERNAL if getattr(channels_cfg, c, None)]
    if wanted:
        unknown = [c for c in wanted if c not in configured]
        if unknown:
            raise ValueError(f"channel not connected: {', '.join(unknown)}")
        return [c for c in _EXTERNAL if c in wanted], True, None
    if len(configured) == 1:
        return configured, True, None
    if configured:
        return (["telegram"] if "telegram" in configured else configured), True, None
    if native_registered(session):
        return ["native"], True, None
    return ["telegram"], False, t("notify.connectTelegram")


def rule_name(place: Place) -> str:
    return t("notify.ruleName", place=place.name)[:64]


def build_rule(place: Place, channels: list[str], enabled: bool) -> AlertRule:
    return AlertRule(
        name=rule_name(place),
        place_id=place.id,
        group_id=None,
        device_id=None,
        all_people=True,
        on_enter=True,
        on_exit=True,
        channels=format_channels(channels),
        cooldown_minutes=0,
        enabled=enabled,
        also_notify_members=False,
        telegram_targets=None,
        created_at=datetime.now(UTC),
    )


def rule_preview(rule: AlertRule, place: Place, hint: str | None) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "place_id": place.id,
        "place_name": place.name,
        "all_people": True,
        "on_enter": rule.on_enter,
        "on_exit": rule.on_exit,
        "channels": parse_channels(rule.channels),
        "cooldown_minutes": rule.cooldown_minutes,
        "enabled": rule.enabled,
        "hint": hint,
    }


def covering_rule(session: Session) -> AlertRule | None:
    """An enabled all-people rule for every place, arrive and leave: it already
    sends every crossing at any new place, so no per-place rule is added."""
    stmt = select(AlertRule).where(
        AlertRule.all_people.is_(True),
        AlertRule.place_id.is_(None),
        AlertRule.enabled.is_(True),
        AlertRule.on_enter.is_(True),
        AlertRule.on_exit.is_(True),
    )
    return session.scalars(stmt.order_by(AlertRule.id).limit(1)).first()


def _covered_preview(rule: AlertRule) -> dict:
    out = {
        "id": rule.id, "name": rule.name, "place_id": None, "place_name": None,
        "all_people": True, "on_enter": rule.on_enter, "on_exit": rule.on_exit,
        "channels": parse_channels(rule.channels), "cooldown_minutes": rule.cooldown_minutes,
        "enabled": rule.enabled, "hint": None,
    }  # fmt: skip
    return {**out, "covered": True}


def add_default_rule(
    session: Session, place: Place, channels_cfg=None, channels: list[str] | None = None
) -> dict:
    """Create the place's default rule in the caller's transaction; its preview.

    When an any-place all-people rule already covers it, nothing is added and
    that rule's preview comes back with `covered: true` (review r116 #7). An
    explicit channel pick still makes a per-place rule: the owner asked for it.
    """
    existing = None if channels else covering_rule(session)
    if existing is not None:
        return _covered_preview(existing)
    channels, enabled, hint = choose_channels(session, channels_cfg, channels)
    rule = build_rule(place, channels, enabled)
    session.add(rule)
    session.flush()
    return rule_preview(rule, place, hint)


def places_without_defaults(session: Session) -> list[Place]:
    """Places no all-people rule covers yet (an any-place one covers them all)."""
    covered = set(
        session.scalars(select(AlertRule.place_id).where(AlertRule.all_people.is_(True))).all()
    )
    if None in covered:
        return []
    return [p for p in session.scalars(select(Place).order_by(Place.name)) if p.id not in covered]


def backfill(session: Session, *, dry_run: bool, place_ids: list[int] | None = None) -> dict:
    """The rules "Notify me" would add (dry run) or adds, one per uncovered place."""
    places = places_without_defaults(session)
    if place_ids is not None:
        places = [p for p in places if p.id in set(place_ids)]
    channels, enabled, hint = choose_channels(session)
    out = []
    for place in places:
        rule = build_rule(place, channels, enabled)
        if not dry_run:
            session.add(rule)
            session.flush()
        out.append(rule_preview(rule, place, hint))
    return {"dry_run": dry_run, "count": len(out), "rules": out}

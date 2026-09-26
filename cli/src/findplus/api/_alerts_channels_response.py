"""Shared channel-status dict builder for the alert channel routes.

Purpose    : `channels_response()` combines telegram/webhook/whatsapp status
             into the one dict every channel route (put/delete on any of the
             three) returns to the browser. Split into its own module so
             routes_alerts_channels.py and routes_alerts_telegram.py can both
             call it without importing each other -- PRI rule 7's 300-line
             cap forced the telegram routes into their own file, and this
             function's callers are split across both.
Outputs    : Masked/derived fields only -- never a bot token, webhook secret
             or WhatsApp apikey in full.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from findplus.alerts.store import load_alerts, mask_phone, mask_token


def mask_url(url: str) -> str:
    """`scheme://host/…abcd` — enough to recognise a webhook, not to call it.

    A webhook URL is a bearer credential: the path segment is usually the only
    thing standing between a stranger and the ability to post fake alerts into
    someone's chat. The browser gets the host (so the user can tell which
    endpoint is configured) and the last four characters (so they can tell two
    endpoints on the same host apart), never the routable path.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return "***"
    tail = (parts.path or "") + (f"?{parts.query}" if parts.query else "")
    if len(tail.strip("/")) <= 4:
        return f"{parts.scheme}://{parts.netloc}/***"
    return f"{parts.scheme}://{parts.netloc}/…{tail[-4:]}"


def _target_labels(tg) -> list[str] | None:
    """One display label per `tg.chat_ids` entry, same order and length.

    UAT6 N15: the Alerts tab used to show a saved Telegram target only as its
    raw id ("-100222"); TelegramCreds.chat_labels (commit 58a4ac7) resolves a
    real "@alice" or a group's title at save time, but channels_response()
    never surfaced it. Falls back to the raw id wherever chat_labels has no
    entry for it (an old file saved before chat_labels existed, or any
    length mismatch) -- store.py's own load path already drops a mismatched
    chat_labels to `()`, so this is the one place that needs the fallback.
    """
    if tg is None:
        return None
    labels = tg.chat_labels
    return [
        labels[i] if i < len(labels) and labels[i] else chat_id
        for i, chat_id in enumerate(tg.chat_ids)
    ]


def channels_response() -> dict[str, Any]:
    ch = load_alerts()
    tg, wh, wa = ch.telegram, ch.webhook, ch.whatsapp
    return {
        "telegram": {
            "configured": tg is not None,
            "bot_username": tg.bot_username if tg else None,
            "chat_title": tg.chat_title if tg else None,
            "bot_token_masked": mask_token(tg.bot_token) if tg else None,
            # Comma string, matching what the targets field PUTs and reads
            # back -- ids/usernames are not secrets, so no masking.
            "targets": ",".join(tg.chat_ids) if tg else None,
            # UAT6 N15: target_ids/target_labels are the same list as
            # `targets`, just not comma-joined -- alerts_telegram_targets.js's
            # chip row needs the raw id (to remove a target) and its display
            # label (to show it) as two parallel arrays, not a string to
            # re-split.
            "target_ids": list(tg.chat_ids) if tg else None,
            "target_labels": _target_labels(tg),
        },
        "webhook": {
            "configured": wh is not None,
            "url": mask_url(wh.url) if wh else None,
            "has_secret": bool(wh and wh.secret),
        },
        # The apikey is never echoed back in any shape, and phone_masked keeps
        # only the country code and the last two digits.
        "whatsapp": {
            "configured": wa is not None,
            "phone_masked": mask_phone(wa.phone) if wa else None,
        },
    }

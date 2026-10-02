"""Send a day summary to the connected channel (Telegram today).

Purpose    : The sending half of the daily summary, shared by the scheduler
             (service/digest.py), POST /api/people/{id}/day/send and
             `findplus day --send`. One path, so the text and the failure
             handling are the same everywhere.
Inputs     : Summary text, the stored channel credentials, an optional sender
             (tests pass a fake; nothing here touches the network on its own).
Outputs    : `SendOutcome` per target: ok, error text with credentials redacted.
Constraints: Never raises for a channel failure (a bad token, a blocked bot, a
             timeout): it comes back as ok=False. The bot token never appears
             in an error. A message is plain text, one send per chat target.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from findplus.alerts.store import AlertsChannels, TelegramCreds, load_alerts
from findplus.redaction import redact_text

#: (text, bot_token, chat_id) -> a DeliveryResult-like object with .success and .error.
Sender = Callable[[str, str, str], object]


@dataclass(frozen=True)
class SendOutcome:
    target: str
    ok: bool
    error: str | None = None


def default_sender(text: str, bot_token: str, chat_id: str):
    from findplus.alerts.channels.telegram import send

    return send(text, bot_token, chat_id)


def telegram_creds(channel: str = "auto", channels: AlertsChannels | None = None):
    """The connected Telegram credentials with at least one chat, else None."""
    if channel not in ("auto", "telegram"):
        return None
    creds: TelegramCreds | None = (channels or load_alerts()).telegram
    return creds if creds and creds.chat_ids else None


def send_to_targets(
    text: str, creds: TelegramCreds, sender: Sender | None = None, targets=None
) -> list[SendOutcome]:
    """Send `text` to each chat target; a failure on one never stops the rest."""
    send = sender or default_sender
    out = []
    for chat_id in targets if targets is not None else creds.chat_ids:
        try:
            result = send(text, creds.bot_token, chat_id)
            ok = bool(getattr(result, "success", False))
            error = None if ok else redact_text(str(getattr(result, "error", None) or "failed"))
        except Exception as exc:  # a channel failure must never crash the caller
            ok, error = False, redact_text(str(exc)[:300])
        out.append(SendOutcome(chat_id, ok, error))
    return out

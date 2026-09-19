"""Telegram alert channel: send a message, and the interactive chat-id capture flow.

Purpose : POST a message to a Telegram bot's chat, and let a user connect a bot
          to Find+ without ever exposing the chat id in a form (the bot
          receives it directly from Telegram when the user presses Start).
Inputs  : A bot token (from BotFather) and, for send(), a chat id.
Outputs : DeliveryResult for send(); a captured-credentials dict for
          telegram_setup(), which also persists it via alerts.store.save_alerts.
Constraints:
    - Never calls deleteWebhook. A 409 from Telegram means the bot already has
      a webhook integration; Find+ must not silently destroy it (ADR-P1-05).
    - No findplus.db import anywhere in this module.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass

import httpx

from findplus.alerts.store import AlertsChannels, TelegramCreds, load_alerts, save_alerts

TELEGRAM_BASE = "https://api.telegram.org/bot"


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    status_code: int | None
    error: str | None


def send(text: str, bot_token: str, chat_id: str, timeout: float = 10.0) -> DeliveryResult:
    """POST a text message. Retries once on a 5xx; raises ValueError on 401/403/400."""
    url = f"{TELEGRAM_BASE}{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    for attempt in range(2):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, json=payload)
        except httpx.TimeoutException:
            return DeliveryResult(success=False, status_code=None, error="timeout")
        if r.status_code == 200:
            return DeliveryResult(success=True, status_code=200, error=None)
        if r.status_code == 401:
            raise ValueError("telegram: invalid token (401)")
        if r.status_code == 403:
            raise ValueError("telegram: bot was blocked or kicked (403)")
        if r.status_code == 400:
            raise ValueError(f"telegram: bad request (400): {r.text[:200]}")
        if r.status_code >= 500 and attempt == 0:
            time.sleep(1)
            continue
        return DeliveryResult(success=False, status_code=r.status_code, error=r.text[:200])
    return DeliveryResult(success=False, status_code=None, error="max retries exceeded")


def _get_me(token: str, client: httpx.Client) -> dict:
    r = client.get(f"{TELEGRAM_BASE}{token}/getMe", timeout=10.0)
    if r.status_code == 409:
        raise RuntimeError(
            "telegram: a webhook is set on this bot; remove it in BotFather or use a different bot"
        )
    if r.status_code == 401:
        raise ValueError("telegram: invalid token (401)")
    r.raise_for_status()
    return r.json()["result"]


def telegram_setup(token: str, wait_seconds: int = 120, poll: int = 2) -> dict:
    """Validate the token, then long-poll getUpdates until the user messages the bot."""
    deadline = time.monotonic() + wait_seconds
    with httpx.Client(timeout=10.0) as client:
        me = _get_me(token, client)
        username = me["username"]
        print(f"Bot @{username} verified. Open t.me/{username}, press Start or send any message.")
        offset = 0
        while time.monotonic() < deadline:
            remaining = int(deadline - time.monotonic())
            r = client.get(
                f"{TELEGRAM_BASE}{token}/getUpdates",
                params={"offset": offset, "timeout": min(poll, remaining)},
                timeout=float(poll + 5),
            )
            if r.status_code == 409:
                raise RuntimeError(
                    "telegram: webhook conflict (409) — remove the webhook in BotFather"
                )
            r.raise_for_status()
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("channel_post")
                if not msg:
                    continue
                chat = msg["chat"]
                creds = TelegramCreds(
                    bot_token=token,
                    chat_id=str(chat["id"]),
                    chat_title=chat.get("title") or chat.get("username") or "private",
                    bot_username=username,
                    captured_at=datetime.datetime.now(datetime.UTC).isoformat(),
                )
                existing = load_alerts()
                save_alerts(AlertsChannels(telegram=creds, webhook=existing.webhook))
                send("Find+ connected ✓", token, str(chat["id"]))
                return {
                    "chat_id": str(chat["id"]),
                    "chat_title": creds.chat_title,
                    "chat_type": chat["type"],
                    "bot_username": username,
                }
            print(f"  Waiting ({remaining} s remaining)...", end="\r", flush=True)
            time.sleep(poll)
    raise TimeoutError(f"no message received within {wait_seconds} s")

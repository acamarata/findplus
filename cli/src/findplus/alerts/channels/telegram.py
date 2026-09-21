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
    - No raised or returned message ever contains the bot token: httpx puts the
      full request URL (which carries the token) into HTTPStatusError, so every
      raise_for_status goes through _http_error instead.
    - bot_token is checked against store.is_valid_bot_token before it is ever
      placed in a URL, in both send() and _get_me(): a malformed token raises
      ValueError immediately and no request is made (blind cap B2). The chat
      id never enters a URL -- send() puts it in the JSON body, which httpx
      encodes on its own.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass

import httpx

from findplus.alerts.store import TelegramCreds, is_valid_bot_token, save_channel

TELEGRAM_BASE = "https://api.telegram.org/bot"


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    status_code: int | None
    error: str | None


def _migrated_chat_id(response: httpx.Response) -> str | None:
    """`parameters.migrate_to_chat_id` from a 400 body, when Telegram sent one.

    Telegram answers 400 when a group has been upgraded to a supergroup and
    hands back the id that replaced it. The old id is dead from then on.
    """
    try:
        params = response.json().get("parameters") or {}
    except ValueError:
        return None
    value = params.get("migrate_to_chat_id")
    return None if value is None else str(value)


def send(text: str, bot_token: str, chat_id: str, timeout: float = 10.0) -> DeliveryResult:
    """POST a text message. Retries once on a 5xx; raises ValueError on 401/403/400.

    A 400 carrying `migrate_to_chat_id` is followed once to the new supergroup
    id rather than reported as a failure: the user did nothing wrong, Telegram
    renumbered their group, and dropping the alert would be the worst outcome.

    Raises ValueError, without making any request, when bot_token is not
    shaped like a real one -- a stored credential can be malformed if
    alerts.json was hand-edited or written by an older version.
    """
    if not is_valid_bot_token(bot_token):
        raise ValueError("telegram: malformed bot token")
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
            migrated = _migrated_chat_id(r)
            if migrated is not None and migrated != chat_id:
                return send(text, bot_token, migrated, timeout=timeout)
            raise ValueError(f"telegram: bad request (400): {r.text[:200]}")
        if r.status_code >= 500 and attempt == 0:
            time.sleep(1)
            continue
        return DeliveryResult(success=False, status_code=r.status_code, error=r.text[:200])
    return DeliveryResult(success=False, status_code=None, error="max retries exceeded")


def _raise_for_status(r: httpx.Response, call: str) -> None:
    """Token-safe replacement for r.raise_for_status() (the URL holds the token)."""
    if r.status_code >= 400:
        raise RuntimeError(f"telegram: {call} returned HTTP {r.status_code}")


def _get_me(token: str, client: httpx.Client) -> dict:
    """GET getMe, or ValueError without a request when the token's shape is wrong.

    Both callers (telegram_setup's own getMe/getUpdates loop and the
    PUT-channels route) already re-check the shape at their own edge to
    return a clean 422/ClickException; this is the backstop that closes the
    same URL-interpolation hole for any caller that does not.
    """
    if not is_valid_bot_token(token):
        raise ValueError("telegram: malformed bot token")
    r = client.get(f"{TELEGRAM_BASE}{token}/getMe", timeout=10.0)
    if r.status_code == 409:
        raise RuntimeError(
            "telegram: a webhook is set on this bot; remove it in BotFather or use a different bot"
        )
    if r.status_code == 401:
        raise ValueError("telegram: invalid token (401)")
    _raise_for_status(r, "getMe")
    return r.json()["result"]


def telegram_setup(token: str, wait_seconds: int = 120, poll: int = 2) -> dict:
    """Validate the token, then long-poll getUpdates until the user messages the bot."""
    deadline = time.monotonic() + wait_seconds
    with httpx.Client(timeout=10.0) as client:
        me = _get_me(token, client)
        username = me["username"]
        _print_setup_instructions(username)
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
                    "telegram: webhook conflict (409), remove the webhook in BotFather"
                )
            _raise_for_status(r, "getUpdates")
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                result = _handle_update(u, token, username)
                if result is not None:
                    return result
            print(f"  Waiting ({remaining} s remaining)...", end="\r", flush=True)
            time.sleep(poll)
    raise TimeoutError(f"no message received within {wait_seconds} s")


def _print_setup_instructions(username: str) -> None:
    print(f"Bot @{username} verified. Open t.me/{username}, press Start or send any message.")
    print(
        f"  For a group or channel: add @{username} to it, then send /start@{username} there. "
        "A bot with group privacy on only sees commands addressed to it, so if nothing "
        f"arrives, turn privacy off in BotFather (/setprivacy, pick @{username}, Disable) "
        "and send the command again."
    )


def _handle_update(u: dict, token: str, username: str) -> dict | None:
    """Process one getUpdates item; None unless it is a usable chat-connect message.

    `my_chat_member` is the only update a group sends when the bot is added
    and privacy mode is on, and `channel_post` the only one a channel sends.
    Without both, group and channel setup hangs until the timeout for no
    visible reason.
    """
    msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member")
    if not msg:
        return None
    chat = msg["chat"]
    creds = TelegramCreds(
        bot_token=token,
        chat_id=str(chat["id"]),
        chat_title=chat.get("title") or chat.get("username") or "private",
        bot_username=username,
        captured_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )
    save_channel(telegram=creds)
    send("Find+ connected ✓", token, str(chat["id"]))
    return {
        "chat_id": str(chat["id"]),
        "chat_title": creds.chat_title,
        "chat_type": chat["type"],
        "bot_username": username,
    }

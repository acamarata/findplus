"""Resolve Telegram targets to numeric ids at save time.

Purpose    : alerts/targets.py only checks the *shape* of a target string, on
             purpose (no network round trip). A person's `@username` cannot
             be used as a sendMessage chat_id at all -- the Bot API only
             resolves `@name` for public groups/channels/supergroups -- so
             before a target list is stored, every `@name` has to become the
             numeric id Telegram actually accepts. This module is that one
             lookup step, called from the PUT routes and the CLI at save
             time; dispatch.py never calls it, because by the time an alert
             fires every stored target is already a numeric id.
Inputs     : The raw comma-separated targets string, and a bot token already
             known to look like a real one (is_valid_bot_token is re-checked
             here too, so this module is safe to call directly).
Outputs    : A tuple of ResolvedTarget(chat_id, label), in input order,
             deduplicated by the resolved id.
Constraints: Raises ValueError naming the exact unresolved `@name` -- Telegram
             bots cannot message someone who has never started them, so there
             is no silent fallback. A 401/409 from Telegram itself raises the
             same way send()/list_chats() already do, distinct from "not
             found" (which falls through to the next resolution step).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from findplus.alerts.channels.telegram import TELEGRAM_BASE, list_chats
from findplus.alerts.store import is_valid_bot_token
from findplus.alerts.targets import parse_targets


@dataclass(frozen=True)
class ResolvedTarget:
    chat_id: str
    label: str


def _label_from_chat(chat: dict, fallback: str) -> str:
    """`@username` when Telegram gave one, else the title, else the input itself."""
    username = chat.get("username")
    if username:
        return f"@{username}"
    return chat.get("title") or fallback


def _get_chat(value: str, token: str, client: httpx.Client) -> tuple[str, str] | None:
    """getChat(@name) -> (numeric id, label); None when Telegram can't find it.

    This resolves a public group/channel's username. Telegram has no lookup
    for a private person's username at all, so a person's `@name` always
    falls through to _match_seen_chat below.
    """
    r = client.get(f"{TELEGRAM_BASE}{token}/getChat", params={"chat_id": value})
    if r.status_code == 401:
        raise ValueError("telegram: invalid token (401)")
    if r.status_code == 409:
        raise RuntimeError(
            "telegram: a webhook is set on this bot; remove it in BotFather or use a different bot"
        )
    if r.status_code != 200:
        return None
    chat = r.json().get("result") or {}
    if "id" not in chat:
        return None
    return str(chat["id"]), _label_from_chat(chat, value)


def _match_seen_chat(chats: list[dict], value: str) -> tuple[str, str] | None:
    """Match '@name' against chats the bot has seen via getUpdates, case-insensitively."""
    target = value[1:].lower()
    for chat in chats:
        if (chat.get("username") or "").lower() == target:
            return chat["id"], _label_from_chat(chat, value)
    return None


def resolve_targets(raw: str, token: str) -> tuple[ResolvedTarget, ...]:
    """Comma-separated targets -> stored (numeric id, label) pairs.

    Numeric ids (including negative group ids) pass through untouched, with
    no request made at all. Each `@name` is resolved with getChat first
    (works for a public group or channel), then matched against the chats
    the bot has seen via getUpdates (a person who has messaged the bot);
    still unresolved raises ValueError naming that exact target.
    """
    if not is_valid_bot_token(token):
        raise ValueError("telegram: malformed bot token")
    parsed = parse_targets(raw)
    resolved: list[ResolvedTarget] = []
    seen_ids: set[str] = set()
    seen_chats: list[dict] | None = None
    client: httpx.Client | None = None
    try:
        for value in parsed:
            if not value.startswith("@"):
                chat_id, label = value, value
            else:
                if client is None:
                    client = httpx.Client(timeout=10.0)
                hit = _get_chat(value, token, client)
                if hit is None:
                    if seen_chats is None:
                        seen_chats = list_chats(token)
                    hit = _match_seen_chat(seen_chats, value)
                if hit is None:
                    raise ValueError(
                        f"{value} hasn't messaged your bot yet. Ask them to send it "
                        "any message, then save again."
                    )
                chat_id, label = hit
            if chat_id not in seen_ids:
                seen_ids.add(chat_id)
                resolved.append(ResolvedTarget(chat_id, label))
    finally:
        if client is not None:
            client.close()
    return tuple(resolved)

"""Telegram alert channel routes: credential management, targets, and the
"Find chat IDs" helper.

Purpose    : Split out of routes_alerts_channels.py (PRI rule 7's 300-line
             cap) once multi-target support (comma-separated chat ids/
             usernames) widened the Telegram surface -- webhook/whatsapp
             stayed behind in routes_alerts_channels.py, which still owns
             the shared `POST /api/alerts/test` dispatcher and mounts this
             module's routes via register().
Outputs    : Masked channel status dicts (channels_response(), shared with
             webhook/whatsapp). ValueError from telegram/_get_me maps to
             400; TimeoutError from the long-poll setup maps to 408; a
             webhook conflict (bot already has one on BotFather) maps to
             409. The bot token is never echoed back in any response.
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC. Handlers close over nothing, so they are module-level
             functions and register() only attaches them.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from findplus.alerts.channels.telegram import _get_me, list_chats, send, telegram_setup
from findplus.alerts.store import TelegramCreds, is_valid_bot_token, load_alerts, save_channel
from findplus.alerts.targets import parse_targets
from findplus.api._alerts_channels_response import channels_response


class TelegramPutBody(BaseModel):
    bot_token: str
    #: Comma-separated targets (numeric ids or @usernames). Omitted keeps
    #: whatever targets are already configured; `chat_id` is a deprecated
    #: single-target alias kept for API back-compat, ignored when `targets`
    #: is also given.
    targets: str | None = None
    chat_id: str | None = None


class TelegramTargetsBody(BaseModel):
    targets: str


class TelegramSetupBody(BaseModel):
    bot_token: str


def put_telegram(body: TelegramPutBody) -> dict[str, Any]:
    import httpx

    # Checked before _get_me ever builds a request: a malformed token is a
    # 422 client error, distinct from the 400 _get_me raises for a real
    # token Telegram itself rejects (blind cap B2).
    if not is_valid_bot_token(body.bot_token):
        raise HTTPException(status_code=422, detail="bot_token must look like a BotFather token")

    with httpx.Client(timeout=10.0) as client:
        try:
            me_result = _get_me(body.bot_token, client)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = load_alerts()
    raw_targets = body.targets if body.targets is not None else body.chat_id
    if raw_targets:
        try:
            chat_ids: tuple[str, ...] = tuple(parse_targets(raw_targets))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        chat_ids = existing.telegram.chat_ids if existing.telegram else ()
    creds = TelegramCreds(
        bot_token=body.bot_token,
        chat_ids=chat_ids,
        chat_title=existing.telegram.chat_title if existing.telegram else "",
        bot_username=me_result["username"],
        captured_at=datetime.now(UTC).isoformat(),
    )
    save_channel(telegram=creds)
    return channels_response()


def put_telegram_targets(body: TelegramTargetsBody) -> dict[str, Any]:
    """Edit the target list alone, no bot-token round trip.

    Lets the Settings/wizard targets field save without ever needing to
    resend the (usually masked) bot token -- `PUT /channels/telegram` above
    stays the one place that verifies a token via getMe.
    """
    existing = load_alerts()
    if not existing.telegram:
        raise HTTPException(status_code=422, detail="Telegram not configured")
    try:
        chat_ids = tuple(parse_targets(body.targets))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_channel(telegram=dataclasses.replace(existing.telegram, chat_ids=chat_ids))
    return channels_response()


def get_telegram_updates() -> dict[str, Any]:
    """ "Find chat IDs": distinct chats seen in the saved bot's pending updates.

    422 when no token is saved yet (nothing to call getUpdates with); the
    Bot API errors (bad token, webhook conflict) map the same way put_telegram
    and post_telegram_setup already do. The token itself never appears in the
    response -- list_chats() only ever returns chat id/type/title/username.
    """
    ch = load_alerts()
    if not ch.telegram:
        raise HTTPException(status_code=422, detail="Telegram not configured")
    try:
        chats = list_chats(ch.telegram.bot_token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"chats": chats}


async def post_telegram_setup(body: TelegramSetupBody, wait: int = 120) -> dict[str, Any]:
    if not is_valid_bot_token(body.bot_token):
        raise HTTPException(status_code=422, detail="bot_token must look like a BotFather token")
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, functools.partial(telegram_setup, body.bot_token, wait_seconds=wait, poll=2)
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=f"no message received within {wait} s") from exc
    except RuntimeError as exc:
        status = 409 if "webhook" in str(exc).lower() else 500
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return result


def delete_telegram() -> Response:
    save_channel(telegram=None)
    return Response(status_code=204)


def telegram_test_results(ch) -> dict[str, Any]:
    """Send the test alert to every configured target; one failure never
    stops the rest. `status`/`error` stay singular (sent/failed/partial, and
    the first failing target's error) so a caller reading only the old shape
    still gets a sane answer; `results` carries the per-target breakdown.
    Called by routes_alerts_channels.post_test for `{"channel": "telegram"}`.
    """
    results = []
    for target in ch.telegram.chat_ids:
        try:
            r = send("Find+ test alert from the dashboard", ch.telegram.bot_token, target)
            results.append(
                {"target": target, "status": "sent" if r.success else "failed", "error": r.error}
            )
        except (ValueError, RuntimeError) as exc:
            results.append({"target": target, "status": "failed", "error": str(exc)})
    statuses = {r["status"] for r in results}
    overall = "sent" if statuses == {"sent"} else "failed" if statuses == {"failed"} else "partial"
    first_error = next((r["error"] for r in results if r["status"] == "failed"), None)
    return {"status": overall, "error": first_error, "results": results}


def register(router: APIRouter) -> None:
    """Attach every Telegram route onto the shared `/api/alerts` router."""
    router.add_api_route("/channels/telegram", put_telegram, methods=["PUT"])
    router.add_api_route("/channels/telegram/targets", put_telegram_targets, methods=["PUT"])
    router.add_api_route("/channels/telegram/updates", get_telegram_updates, methods=["GET"])
    router.add_api_route("/channels/telegram/setup", post_telegram_setup, methods=["POST"])
    router.add_api_route("/channels/telegram", delete_telegram, methods=["DELETE"], status_code=204)

"""Alert channel routes: Telegram/webhook credential management and test sends.

Purpose    : Let the dashboard and CLI configure and test the two alert
             channels without ever exposing a full bot token or secret back
             to the browser.
Outputs    : Masked channel status dicts. ValueError from telegram/_get_me
             maps to 400; TimeoutError from the long-poll setup maps to 408;
             a webhook conflict (bot already has one) maps to 409.
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC (routes_alerts is never in that set). Handlers close
             over nothing, so they are module-level functions and
             build_router only registers them (E13 loop-1 function-cap
             refactor; routes and signatures unchanged).
"""

from __future__ import annotations

import asyncio
import functools
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from findplus.alerts.channels.telegram import _get_me, send, telegram_setup
from findplus.alerts.channels.webhook import build_payload, is_valid_url, send_webhook
from findplus.alerts.store import (
    TelegramCreds,
    WebhookCreds,
    WhatsappCreds,
    is_valid_phone,
    load_alerts,
    mask_phone,
    mask_token,
    save_channel,
)


class TelegramPutBody(BaseModel):
    bot_token: str
    chat_id: str | None = None


class TelegramSetupBody(BaseModel):
    bot_token: str


class WebhookPutBody(BaseModel):
    url: str
    secret: str | None = None


class WhatsappPutBody(BaseModel):
    phone: str
    apikey: str


class AlertTestBody(BaseModel):
    channel: Literal["telegram", "webhook", "whatsapp", "native"]


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


def _channels_response() -> dict[str, Any]:
    ch = load_alerts()
    tg, wh, wa = ch.telegram, ch.webhook, ch.whatsapp
    return {
        "telegram": {
            "configured": tg is not None,
            "bot_username": tg.bot_username if tg else None,
            "chat_title": tg.chat_title if tg else None,
            "bot_token_masked": mask_token(tg.bot_token) if tg else None,
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


def get_channels() -> dict[str, Any]:
    return _channels_response()


def put_telegram(body: TelegramPutBody) -> dict[str, Any]:
    import httpx

    with httpx.Client(timeout=10.0) as client:
        try:
            me_result = _get_me(body.bot_token, client)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = load_alerts()
    creds = TelegramCreds(
        bot_token=body.bot_token,
        chat_id=body.chat_id or (existing.telegram.chat_id if existing.telegram else ""),
        chat_title=existing.telegram.chat_title if existing.telegram else "",
        bot_username=me_result["username"],
        captured_at=datetime.now(UTC).isoformat(),
    )
    save_channel(telegram=creds)
    return _channels_response()


async def post_telegram_setup(body: TelegramSetupBody, wait: int = 120) -> dict[str, Any]:
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


def put_webhook(body: WebhookPutBody) -> dict[str, Any]:
    if not is_valid_url(body.url):
        raise HTTPException(status_code=422, detail="url must be https or http loopback")
    save_channel(webhook=WebhookCreds(url=body.url, secret=body.secret))
    return _channels_response()


def delete_webhook() -> Response:
    save_channel(webhook=None)
    return Response(status_code=204)


def put_whatsapp(body: WhatsappPutBody) -> dict[str, Any]:
    # Validate before any write, like put_webhook. Unlike put_telegram there is
    # no verification round-trip: CallMeBot has no side-effect-free call that
    # would tell a good key from a bad one.
    if not is_valid_phone(body.phone):
        raise HTTPException(status_code=422, detail="phone must be E.164, e.g. +34123123123")
    save_channel(whatsapp=WhatsappCreds(phone=body.phone, apikey=body.apikey))
    return _channels_response()


def delete_whatsapp() -> Response:
    save_channel(whatsapp=None)
    return Response(status_code=204)


def post_test(body: AlertTestBody) -> dict[str, Any]:
    ch = load_alerts()
    if body.channel == "telegram":
        if not ch.telegram:
            raise HTTPException(status_code=422, detail="Telegram not configured")
        try:
            result = send(
                "Find+ test alert from the dashboard",
                ch.telegram.bot_token,
                ch.telegram.chat_id,
            )
        except (ValueError, RuntimeError) as exc:
            return {"status": "failed", "error": str(exc)}
    elif body.channel == "webhook":
        if not ch.webhook:
            raise HTTPException(status_code=422, detail="Webhook not configured")
        payload = build_payload(
            "ENTER",
            "device",
            "test",
            "Test Tag",
            0,
            "Test Place",
            datetime.now(UTC),
            None,
            None,  # fetched_at is unknown for this sample, so lag_minutes must be null too
            "high",
            "This is a test alert.",
        )
        result = send_webhook(payload, ch.webhook.url, ch.webhook.secret)
    elif body.channel == "whatsapp":
        if not ch.whatsapp:
            raise HTTPException(status_code=422, detail="WhatsApp not configured")
        from findplus.alerts.channels.whatsapp_callmebot import send as wa_send

        result = wa_send(
            "Find+ test alert from the dashboard", ch.whatsapp.phone, ch.whatsapp.apikey
        )
    else:
        # native has no outbound send: the desktop app drains a queue, and
        # nothing here can put a row in it for a test (E8-T4).
        raise HTTPException(status_code=422, detail="native alerts cannot be tested from here")
    return {"status": "sent" if result.success else "failed", "error": result.error}


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/alerts", tags=["alerts"])
    router.add_api_route("/channels", get_channels, methods=["GET"])
    router.add_api_route("/channels/telegram", put_telegram, methods=["PUT"])
    router.add_api_route("/channels/telegram/setup", post_telegram_setup, methods=["POST"])
    router.add_api_route("/channels/telegram", delete_telegram, methods=["DELETE"], status_code=204)
    router.add_api_route("/channels/webhook", put_webhook, methods=["PUT"])
    router.add_api_route("/channels/webhook", delete_webhook, methods=["DELETE"], status_code=204)
    router.add_api_route("/channels/whatsapp", put_whatsapp, methods=["PUT"])
    router.add_api_route("/channels/whatsapp", delete_whatsapp, methods=["DELETE"], status_code=204)
    router.add_api_route("/test", post_test, methods=["POST"])
    return router

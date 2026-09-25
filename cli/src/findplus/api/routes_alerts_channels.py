"""Alert channel routes: webhook/WhatsApp credential management and the
shared test-send dispatcher.

Purpose    : Let the dashboard and CLI configure and test the alert channels
             without ever exposing a full webhook secret or WhatsApp apikey
             back to the browser. Telegram's own routes (PRI rule 7's
             300-line cap, widened by multi-target support) live in
             routes_alerts_telegram.py; build_router() mounts both.
Outputs    : Masked channel status dicts (channels_response(), shared with
             the telegram routes).
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC (routes_alerts is never in that set). Handlers close
             over nothing, so they are module-level functions and
             build_router only registers them (E13 loop-1 function-cap
             refactor; routes and signatures unchanged).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from findplus.alerts.channels.webhook import build_payload, is_valid_url, send_webhook
from findplus.alerts.store import (
    WebhookCreds,
    WhatsappCreds,
    is_valid_apikey,
    is_valid_phone,
    load_alerts,
    save_channel,
)
from findplus.api import routes_alerts_telegram
from findplus.api._alerts_channels_response import channels_response, mask_url

__all__ = ["build_router", "mask_url"]


class WebhookPutBody(BaseModel):
    url: str
    secret: str | None = None


class WhatsappPutBody(BaseModel):
    phone: str
    apikey: str


class AlertTestBody(BaseModel):
    channel: Literal["telegram", "webhook", "whatsapp", "native"]


def get_channels() -> dict[str, Any]:
    return channels_response()


def put_webhook(body: WebhookPutBody) -> dict[str, Any]:
    if not is_valid_url(body.url):
        raise HTTPException(status_code=422, detail="url must be https or http loopback")
    save_channel(webhook=WebhookCreds(url=body.url, secret=body.secret))
    return channels_response()


def delete_webhook() -> Response:
    save_channel(webhook=None)
    return Response(status_code=204)


def put_whatsapp(body: WhatsappPutBody) -> dict[str, Any]:
    # Validate before any write, like put_webhook. Unlike telegram there is
    # no verification round-trip: CallMeBot has no side-effect-free call that
    # would tell a good key from a bad one.
    if not is_valid_phone(body.phone):
        raise HTTPException(status_code=422, detail="phone must be E.164, e.g. +34123123123")
    if not is_valid_apikey(body.apikey):
        raise HTTPException(
            status_code=422, detail="apikey must be alphanumeric, at least 4 characters"
        )
    save_channel(whatsapp=WhatsappCreds(phone=body.phone, apikey=body.apikey))
    return channels_response()


def delete_whatsapp() -> Response:
    save_channel(whatsapp=None)
    return Response(status_code=204)


def post_test(body: AlertTestBody) -> dict[str, Any]:
    ch = load_alerts()
    if body.channel == "telegram":
        if not ch.telegram or not ch.telegram.chat_ids:
            raise HTTPException(status_code=422, detail="Telegram not configured")
        return routes_alerts_telegram.telegram_test_results(ch)
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
    routes_alerts_telegram.register(router)
    router.add_api_route("/channels/webhook", put_webhook, methods=["PUT"])
    router.add_api_route("/channels/webhook", delete_webhook, methods=["DELETE"], status_code=204)
    router.add_api_route("/channels/whatsapp", put_whatsapp, methods=["PUT"])
    router.add_api_route("/channels/whatsapp", delete_whatsapp, methods=["DELETE"], status_code=204)
    router.add_api_route("/test", post_test, methods=["POST"])
    return router

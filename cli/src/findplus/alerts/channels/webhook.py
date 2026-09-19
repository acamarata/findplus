"""Webhook alert channel: HMAC-signed JSON POST to a user-configured URL.

Purpose : Deliver an alert event as JSON to any endpoint that can accept an
          incoming webhook (interim path for WhatsApp and other integrations,
          per D9).
Inputs  : Event fields (build_payload) and the destination URL/secret.
Outputs : DeliveryResult; an X-FindPlus-Signature header when a secret is set.
Constraints: No findplus.db import anywhere in this module.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import re

import httpx

from findplus.alerts.channels.telegram import DeliveryResult

#: https anywhere, or plain http only to a real loopback HOST. The host part is
#: anchored (\Z, a port, or a path) so "http://localhost.example.com" is rejected.
_URL_RE = re.compile(
    r"https://\S+\Z|http://(?:127(?:\.\d{1,3}){3}|localhost|\[::1\])(?::\d+)?(?:/\S*)?\Z",
    re.IGNORECASE,
)


def is_valid_url(url: str) -> bool:
    """True for an https URL or an http URL pointing at loopback (api-contract.md)."""
    return bool(_URL_RE.fullmatch(url.strip()))


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def build_payload(
    event: str,
    kind: str,
    subject_id: str | int,
    subject_name: str,
    place_id: int,
    place_name: str,
    observed_at: datetime.datetime,
    fetched_at: datetime.datetime | None,
    lag_minutes: int,
    confidence: str,
    note: str,
) -> dict:
    return {
        "event": event,
        "kind": kind,
        "subject": {"id": subject_id, "name": subject_name},
        "place": {"id": place_id, "name": place_name},
        "observed_at": observed_at.isoformat(),
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "lag_minutes": lag_minutes,
        "confidence": confidence,
        "note": note,
        "sent_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def send_webhook(
    payload: dict, url: str, secret: str | None = None, timeout: float = 10.0
) -> DeliveryResult:
    body = json.dumps(payload, default=str).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["X-FindPlus-Signature"] = _sign(body, secret)
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, content=body, headers=headers)
        if 200 <= r.status_code < 300:
            return DeliveryResult(success=True, status_code=r.status_code, error=None)
        return DeliveryResult(success=False, status_code=r.status_code, error=r.text[:200])
    except httpx.TimeoutException:
        return DeliveryResult(success=False, status_code=None, error="timeout")
    except Exception as exc:
        return DeliveryResult(success=False, status_code=None, error=str(exc)[:200])

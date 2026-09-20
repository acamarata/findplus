"""WhatsApp alert channel over CallMeBot's free personal API.

Purpose : Send one alert line-set to the user's own WhatsApp number through
          CallMeBot, the relay D-P2-1 picked because it needs no WhatsApp
          Business account.
Inputs  : The rendered message, the user's E.164 phone number and the API key
          CallMeBot replied with during setup.
Outputs : A DeliveryResult, re-used from telegram.py -- never a raised error.
Constraints:
    - No database import (importable under the network-block test fixture).
    - send() never raises. CallMeBot answers 200 with plain text whatever
      happened, so a bad key is a failed DeliveryResult like any other, the way
      webhook.py behaves and unlike telegram.py's raise-on-4xx.
    - No value from the request ever reaches DeliveryResult.error: a non-200
      stores only its status, and a 200 "Error" body is stripped of its
      apikey=/phone= fragments BEFORE truncation.
    - No retry. Ruling F2 (p1/e15/review-log.md) forbids one at the dispatch
      layer, and CallMeBot's free tier documents no retry contract.
"""

from __future__ import annotations

import re

import httpx

from findplus.alerts.channels.telegram import DeliveryResult

CALLMEBOT_BASE = "https://api.callmebot.com/whatsapp.php"

#: Strips apikey=/phone= query fragments out of a CallMeBot error body before it
#: is ever stored or logged. Same redaction shape logging_setup.py's
#: _TOKEN_PATTERN uses for a request URL, applied here to the response body.
_QUERY_SECRET_RE = re.compile(r"(?:apikey|phone)=[^&\s]+")


def _strip_query_secrets(body: str) -> str:
    return _QUERY_SECRET_RE.sub("<redacted>", body)


def send(text: str, phone: str, apikey: str, timeout: float = 10.0) -> DeliveryResult:
    """GET CallMeBot's whatsapp.php with the message. Never raises, never retries."""
    # QueryParams, never manual concatenation: the leading '+' of an E.164 number
    # has to arrive as %2B, and a server reading a bare '+' as a space would send
    # the alert to the wrong number.
    params = httpx.QueryParams({"phone": phone, "text": text, "apikey": apikey})
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(CALLMEBOT_BASE, params=params)
    except httpx.TimeoutException:
        return DeliveryResult(success=False, status_code=None, error="timeout")
    if r.status_code != 200:
        # The status only. The body of a non-200 is an unbounded upstream page,
        # and the request URL carries the key.
        return DeliveryResult(
            success=False, status_code=r.status_code, error=f"HTTP {r.status_code}"
        )
    if r.text.strip().lower().startswith("error"):
        # CallMeBot's documented failure shape is a 200 whose body begins
        # "Error: apikey is invalid..." and often echoes the query string back.
        return DeliveryResult(
            success=False, status_code=200, error=_strip_query_secrets(r.text)[:200]
        )
    return DeliveryResult(success=True, status_code=200, error=None)

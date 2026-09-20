"""alerts/channels/whatsapp_callmebot.py: send() against a fully mocked httpx.Client.

Purpose : Pin the CallMeBot request shape and, above all, that nothing from the
          request ever reaches DeliveryResult.error (loop-2 F14).
Constraints: No socket is opened; httpx.Client is patched exactly the way
          test_telegram.py patches it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from findplus.alerts.channels.telegram import DeliveryResult
from findplus.alerts.channels.whatsapp_callmebot import (
    CALLMEBOT_BASE,
    _strip_query_secrets,
    send,
)

APIKEY = "1234567890"
PHONE = "+34123123123"
ERROR_BODY = f"Error: apikey is invalid apikey={APIKEY}&phone=%2B34123123123"


def _response(status_code: int, text: str = "Message queued") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def _client(resp):
    """Patch context manager returning a client whose get() yields `resp`."""
    mock = patch("findplus.alerts.channels.whatsapp_callmebot.httpx.Client")
    started = mock.start()
    started.return_value.__enter__.return_value.get.return_value = resp
    return mock, started.return_value.__enter__.return_value


def test_send_succeeds_on_a_200_without_an_error_body() -> None:
    mock, _ = _client(_response(200))
    try:
        result = send("hi", PHONE, APIKEY)
    finally:
        mock.stop()
    assert result == DeliveryResult(True, 200, None)


def test_send_fails_on_a_non_200_and_stores_only_the_status() -> None:
    mock, _ = _client(_response(500, text=f"<html>oops {APIKEY}</html>"))
    try:
        result = send("hi", PHONE, APIKEY)
    finally:
        mock.stop()
    assert result.success is False
    assert result.error == "HTTP 500"
    assert APIKEY not in result.error


def test_send_fails_on_a_200_error_body_without_leaking_the_key_or_number() -> None:
    mock, _ = _client(_response(200, text=ERROR_BODY))
    try:
        result = send("hi", PHONE, APIKEY)
    finally:
        mock.stop()
    assert result.success is False
    assert result.status_code == 200
    assert "apikey=" not in result.error
    assert "phone=" not in result.error
    assert APIKEY not in result.error
    assert PHONE not in result.error
    assert "Error: apikey is invalid" in result.error


def test_an_error_body_is_redacted_before_truncation_not_after() -> None:
    """Truncating first could cut a key in half and store the visible half."""
    padding = "x" * 250
    body = f"Error: {padding} apikey={APIKEY}"
    mock, _ = _client(_response(200, text=body))
    try:
        result = send("hi", PHONE, APIKEY)
    finally:
        mock.stop()
    assert len(result.error) <= 200
    assert "1234" not in result.error


def test_a_capitalised_or_lowercase_error_body_still_fails() -> None:
    for text in ("error: phone number not registered", "ERROR: nope"):
        mock, _ = _client(_response(200, text=text))
        try:
            result = send("hi", PHONE, APIKEY)
        finally:
            mock.stop()
        assert result.success is False, text


def test_send_maps_a_timeout_to_the_shared_shape() -> None:
    mock = patch("findplus.alerts.channels.whatsapp_callmebot.httpx.Client")
    started = mock.start()
    started.return_value.__enter__.return_value.get.side_effect = httpx.TimeoutException("slow")
    try:
        result = send("hi", PHONE, APIKEY)
    finally:
        mock.stop()
    assert result == DeliveryResult(False, None, "timeout")


def test_the_request_percent_encodes_the_plus_the_space_and_the_newline() -> None:
    mock, client = _client(_response(200))
    try:
        send("a b\nc", PHONE, APIKEY)
    finally:
        mock.stop()
    url, kwargs = client.get.call_args[0][0], client.get.call_args[1]
    assert url == CALLMEBOT_BASE
    encoded = str(kwargs["params"])
    assert "phone=%2B34123123123" in encoded
    assert "%0A" in encoded
    assert "+" in encoded or "%20" in encoded  # a space encodes as either
    assert " " not in encoded


def test_send_never_retries() -> None:
    mock, client = _client(_response(500))
    try:
        send("hi", PHONE, APIKEY)
    finally:
        mock.stop()
    assert client.get.call_count == 1


def test_strip_query_secrets_removes_both_fragments() -> None:
    cleaned = _strip_query_secrets(f"boom apikey={APIKEY}&phone={PHONE} tail")
    assert cleaned == "boom <redacted>&<redacted> tail"


def test_mask_phone_shows_only_the_country_code_and_the_last_two_digits() -> None:
    from findplus.alerts.store import mask_phone

    masked = mask_phone(PHONE)
    assert masked == "+34…23"
    assert "1231231" not in masked


def test_mask_phone_refuses_to_half_mask_a_short_number() -> None:
    from findplus.alerts.store import mask_phone

    assert mask_phone("+123") == "***"


def test_is_valid_phone_accepts_e164_and_rejects_the_near_misses() -> None:
    from findplus.alerts.store import is_valid_phone

    assert is_valid_phone(PHONE)
    assert not is_valid_phone("34123123123")  # no leading +
    assert not is_valid_phone("+0123456789")  # country code cannot start with 0
    assert not is_valid_phone("+341231")  # too short
    assert not is_valid_phone("+3412312312345678")  # too long
    assert not is_valid_phone("+3412 3123123")  # no spaces


@pytest.mark.posix_only
def test_alerts_json_round_trips_whatsapp_like_the_other_two(tmp_path, monkeypatch) -> None:
    from findplus.alerts import store

    path = tmp_path / "alerts.json"
    monkeypatch.setattr(store, "_alerts_path", lambda: path)
    store.save_alerts(
        store.AlertsChannels(whatsapp=store.WhatsappCreds(phone=PHONE, apikey=APIKEY))
    )
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = store.load_alerts()
    assert loaded.whatsapp == store.WhatsappCreds(phone=PHONE, apikey=APIKEY)
    assert loaded.telegram is None
    store.save_alerts(store.AlertsChannels())
    assert store.load_alerts().whatsapp is None


def test_the_two_whatsapp_honesty_sentences_are_in_notices() -> None:
    from findplus import honesty

    assert honesty.NOTICES["whatsapp_relay"] == honesty.WHATSAPP_RELAY
    assert honesty.NOTICES["whatsapp_setup"] == honesty.WHATSAPP_SETUP
    assert "CallMeBot" in honesty.WHATSAPP_RELAY
    assert "+34 623 91 22 04" in honesty.WHATSAPP_SETUP

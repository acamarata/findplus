"""Credentials must not reach alert_deliveries.error, which CF-14 now displays.

CR-C-E1 F13: channels/webhook.py stores `str(exc)[:200]` and dispatch stored
`str(exc)[:500]`; httpx status errors embed the request URL, and a CallMeBot
webhook carries its apikey in the query string, so an ordinary 401 wrote the
key into the database in clear text and the dashboard then rendered it.
"""

from __future__ import annotations

import pytest

from findplus.redaction import redact_text

CALLMEBOT = "https://api.callmebot.com/whatsapp.php?phone=15550123&apikey=874216&text=hi"


def test_a_secret_query_parameter_is_masked() -> None:
    out = redact_text(f"Client error '401 Unauthorized' for url '{CALLMEBOT}'")
    assert "874216" not in out
    assert "<redacted>" in out
    assert "phone=15550123" in out, "non-secret parameters stay, or the error is unreadable"


@pytest.mark.parametrize("name", ["token", "api_key", "access_token", "secret", "sig", "password"])
def test_every_known_secret_parameter_name_is_masked(name: str) -> None:
    assert "s3cr3t" not in redact_text(f"POST https://h.example/x?{name}=s3cr3t failed")


def test_a_non_secret_parameter_survives() -> None:
    assert "chat=general" in redact_text("GET https://h.example/x?chat=general -> 500")


def test_url_userinfo_is_masked() -> None:
    out = redact_text("connect to https://alice:hunter2@hooks.example.com/path failed")
    assert "hunter2" not in out
    assert "alice" in out


def test_a_bare_bot_token_is_masked() -> None:
    token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz123456789"
    assert token not in redact_text(f"telegram rejected {token}")


def test_ordinary_errors_pass_through_unchanged() -> None:
    for text in ("timeout", "Connection refused", "500 Internal Server Error"):
        assert redact_text(text) == text


def test_empty_and_none_pass_through() -> None:
    assert redact_text(None) is None
    assert redact_text("") == ""


def test_the_delivery_status_path_redacts_before_storing(monkeypatch) -> None:
    """The choke point: every channel's error reaches the row through _status_for."""
    from findplus.alerts import dispatch_send

    class _Rule:
        channel = "webhook"

    class _Result:
        success = False
        error = f"Client error '401 Unauthorized' for url '{CALLMEBOT}'"

    monkeypatch.setattr(dispatch_send, "render_message", lambda *a, **k: "msg")
    monkeypatch.setattr(dispatch_send, "_send", lambda *a, **k: _Result())

    status, err = dispatch_send._status_for(_Rule(), object(), "device", None, None)

    assert status == "failed"
    assert "874216" not in err
    assert "<redacted>" in err


def test_an_exception_message_is_redacted_too(monkeypatch) -> None:
    from findplus.alerts import dispatch_send

    class _Rule:
        channel = "webhook"

    def _boom(*a, **k):
        raise RuntimeError(f"POST {CALLMEBOT} blew up")

    monkeypatch.setattr(dispatch_send, "render_message", lambda *a, **k: "msg")
    monkeypatch.setattr(dispatch_send, "_send", _boom)

    status, err = dispatch_send._status_for(_Rule(), object(), "device", None, None)

    assert status == "failed"
    assert "874216" not in err

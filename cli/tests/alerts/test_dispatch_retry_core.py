"""dispatch_core.py: pure retry classification and scheduling (no DB, no clock)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.alerts.dispatch_core import (
    classify_new_delivery,
    compute_next_attempt_at,
    is_transient_failure,
)

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)


def test_is_transient_failure_cases() -> None:
    assert is_transient_failure(429, "rate limited") is True
    assert is_transient_failure(500, "server error") is True
    assert is_transient_failure(503, "unavailable") is True
    assert is_transient_failure(None, "timeout") is True
    assert is_transient_failure(400, "bad request") is False
    assert is_transient_failure(404, "not found") is False
    assert is_transient_failure(None, "malformed phone") is False
    assert is_transient_failure(200, "Error: apikey is invalid") is False


def test_is_transient_failure_connection_level_errors() -> None:
    """R1: a connection-level failure never carries a status code (httpx
    raises before a response exists), but it is still a transient condition
    -- only a credential/shape problem the channel caught before ever
    opening a connection stays permanent at status_code=None."""
    assert is_transient_failure(None, "[Errno 61] Connection refused") is True
    assert is_transient_failure(None, "Connection reset by peer") is True
    assert is_transient_failure(None, "[Errno 8] nodename nor servname provided") is True
    ssl_error = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
    assert is_transient_failure(None, ssl_error) is True
    assert is_transient_failure(None, "All connection attempts failed") is True


def test_is_transient_failure_telegram_credential_errors_stay_permanent() -> None:
    """telegram.py's send() raises these with no status code (dispatch_send.py's
    except-Exception catch produces the same (None, str(exc)) shape a real
    connection error would) -- the "telegram: " prefix is what still tells
    them apart from a genuine network failure."""
    assert is_transient_failure(None, "telegram: malformed bot token") is False
    assert is_transient_failure(None, "telegram: invalid token (401)") is False
    assert is_transient_failure(None, "telegram: bot was blocked or kicked (403)") is False
    assert is_transient_failure(None, "telegram: bad request (400): oops") is False
    assert is_transient_failure(None, "malformed apikey") is False
    assert is_transient_failure(None, None) is False


def test_compute_next_attempt_at_follows_the_ladder() -> None:
    assert compute_next_attempt_at(NOW, 1, NOW, None) == NOW + timedelta(minutes=1)
    assert compute_next_attempt_at(NOW, 2, NOW, None) == NOW + timedelta(minutes=5)
    assert compute_next_attempt_at(NOW, 3, NOW, None) == NOW + timedelta(minutes=30)


def test_retry_after_only_ever_lengthens_the_wait() -> None:
    # 10 s is shorter than the 1-minute ladder value, so the ladder wins.
    assert compute_next_attempt_at(NOW, 1, NOW, 10) == NOW + timedelta(minutes=1)
    # 10 min beats the 1-minute ladder value.
    assert compute_next_attempt_at(NOW, 1, NOW, 600) == NOW + timedelta(minutes=10)


def test_retry_after_is_capped_at_thirty_minutes_from_first_failure() -> None:
    assert compute_next_attempt_at(NOW, 1, NOW, 3600) == NOW + timedelta(minutes=30)


def test_classify_new_delivery_only_reclassifies_a_transient_failure() -> None:
    assert classify_new_delivery("sent", None, 200, None, NOW) == ("sent", 1, None)
    assert classify_new_delivery("skipped", "x not configured", None, None, NOW) == (
        "skipped",
        1,
        None,
    )
    assert classify_new_delivery("queued", None, None, None, NOW) == ("queued", 1, None)
    assert classify_new_delivery("failed", "bad request", 400, None, NOW) == ("failed", 1, None)

    status, attempts, next_at = classify_new_delivery("failed", "timeout", None, None, NOW)
    assert status == "retrying"
    assert attempts == 1
    assert next_at == NOW + timedelta(minutes=1)

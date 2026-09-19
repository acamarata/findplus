"""alerts/store.py: file mode, roundtrip, corrupted-file, mask, and redaction."""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from findplus.alerts.store import (
    AlertsChannels,
    TelegramCreds,
    WebhookCreds,
    load_alerts,
    mask_token,
    save_alerts,
)


@pytest.fixture(autouse=True)
def _isolated_alerts_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    alerts_file = tmp_path / "alerts.json"
    monkeypatch.setattr(
        "findplus.alerts.store.get_settings",
        lambda: types.SimpleNamespace(alerts_file=alerts_file),
    )
    return alerts_file


@pytest.mark.posix_only
def test_save_creates_file_0600(_isolated_alerts_file: Path) -> None:
    creds = TelegramCreds(
        bot_token="123", chat_id="1", chat_title="t", bot_username="b", captured_at="now"
    )
    save_alerts(AlertsChannels(telegram=creds))
    assert _isolated_alerts_file.stat().st_mode & 0o777 == 0o600


def test_load_roundtrip(_isolated_alerts_file: Path) -> None:
    creds = TelegramCreds(
        bot_token="123", chat_id="1", chat_title="t", bot_username="b", captured_at="now"
    )
    save_alerts(AlertsChannels(telegram=creds))
    loaded = load_alerts()
    assert loaded.telegram == creds


def test_load_missing_returns_empty(_isolated_alerts_file: Path) -> None:
    assert load_alerts() == AlertsChannels(None, None)


def test_load_corrupted_returns_empty(_isolated_alerts_file: Path) -> None:
    _isolated_alerts_file.parent.mkdir(parents=True, exist_ok=True)
    _isolated_alerts_file.write_text("not json")
    assert load_alerts() == AlertsChannels()


def test_save_webhook(_isolated_alerts_file: Path) -> None:
    creds = WebhookCreds(url="https://example.com", secret="s3cr3t")
    save_alerts(AlertsChannels(webhook=creds))
    loaded = load_alerts()
    assert loaded.webhook == creds


def test_mask_token_normal() -> None:
    masked = mask_token("1234567890:ABCdefGHI_jklMNO-pqrSTUvwxyz0123")
    assert masked.startswith("1234")
    assert masked.endswith("0123")


def test_mask_token_short() -> None:
    assert mask_token("abc") == "***"


def test_redaction_telegram_token() -> None:
    # 35 chars after the colon, matching the real Telegram token secret length
    # (\d{8,10}:[A-Za-z0-9_-]{35}\b) -- the ticket's own 34-char sample string
    # does not match its own pattern; this one does.
    from findplus.logging_setup import _redact

    token = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"
    out = _redact(None, "test", {"msg": f"token {token} leaked"})
    assert token not in out["msg"]
    assert "<redacted>" in out["msg"]

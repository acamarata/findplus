"""Credential store for alert channels (Telegram, webhook).

Purpose : Read/write ~/.findplus/alerts.json (0600) holding channel credentials.
Inputs  : AlertsChannels dataclass tree; the state-dir path from Settings.alerts_file.
Outputs : alerts.json on disk, atomic-written.
Constraints:
    - No findplus.db import here (importable under the network-block test fixture).
    - Atomic write: .tmp (created 0600) -> os.replace, so the credentials are
      never on disk at the default umask, not even for one syscall.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib

from findplus.config import get_settings


@dataclasses.dataclass(frozen=True)
class TelegramCreds:
    bot_token: str
    chat_id: str
    chat_title: str
    bot_username: str
    captured_at: str


@dataclasses.dataclass(frozen=True)
class WebhookCreds:
    url: str
    secret: str | None


@dataclasses.dataclass(frozen=True)
class AlertsChannels:
    telegram: TelegramCreds | None = None
    webhook: WebhookCreds | None = None


def _alerts_path() -> pathlib.Path:
    return get_settings().alerts_file


def load_alerts() -> AlertsChannels:
    """Read alerts.json. Missing or corrupted file returns an empty AlertsChannels."""
    path = _alerts_path()
    if not path.exists():
        return AlertsChannels()
    try:
        raw = json.loads(path.read_text())
        ch = raw.get("channels", {})
        tg = ch.get("telegram")
        wh = ch.get("webhook")
        return AlertsChannels(
            telegram=TelegramCreds(**tg) if tg else None,
            webhook=WebhookCreds(**wh) if wh else None,
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # ValueError covers JSONDecodeError and a binary file's UnicodeDecodeError.
        return AlertsChannels()


def save_alerts(channels: AlertsChannels) -> None:
    """Atomically write alerts.json at mode 0600."""
    path = _alerts_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data: dict = {"channels": {}}
    if channels.telegram:
        data["channels"]["telegram"] = dataclasses.asdict(channels.telegram)
    if channels.webhook:
        data["channels"]["webhook"] = dataclasses.asdict(channels.webhook)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def mask_token(token: str) -> str:
    """First 4 + last 4 characters, else '***' for a token too short to mask safely."""
    return "***" if len(token) < 8 else token[:4] + "…" + token[-4:]

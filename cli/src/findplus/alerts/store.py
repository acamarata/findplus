"""Credential store for alert channels (Telegram, webhook, WhatsApp).

Purpose : Read/write ~/.findplus/alerts.json (0600) holding channel credentials.
Inputs  : AlertsChannels dataclass tree; the state-dir path from Settings.alerts_file.
Outputs : alerts.json on disk, atomic-written.
Constraints:
    - No database import here (importable under the network-block test fixture).
    - Atomic write: .tmp (created 0600) -> os.replace, so the credentials are
      never on disk at the default umask, not even for one syscall.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re

from findplus.config import get_settings


@dataclasses.dataclass(frozen=True)
class TelegramCreds:
    bot_token: str
    #: One or more targets: a numeric user/group/supergroup id, or an
    #: '@username'. A tuple, not a list, so the frozen dataclass stays
    #: hashable/immutable like its sibling fields (alerts/targets.py owns
    #: parsing and validation). Old alerts.json files on disk hold a single
    #: `"chat_id": "..."` string instead -- load_alerts() below converts that
    #: to a one-item tuple on read, so an upgraded install keeps sending to
    #: the same chat without the user doing anything.
    chat_ids: tuple[str, ...]
    chat_title: str
    bot_username: str
    captured_at: str
    #: One label per chat_ids entry, same order and length -- '@name' for a
    #: person, a group/channel's title, or the id itself when nothing better
    #: is known (alerts/channels/telegram_targets.py resolves these at save
    #: time). Empty on a file saved before this field existed, or on any
    #: mismatch with chat_ids -- callers fall back to showing the raw id.
    chat_labels: tuple[str, ...] = ()

    @property
    def chat_id(self) -> str:
        """The first target, for the handful of call sites that only ever
        send to one place (CLI --channel test, the delivery-log fallback).
        """
        return self.chat_ids[0] if self.chat_ids else ""


#: BotFather's own shape: a numeric bot id, a colon, then a 30+ char secret
#: (`[A-Za-z0-9_-]`). Shape-only -- it never proves the token is live, only
#: that it is worth building a Telegram URL for.
_BOT_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


def is_valid_bot_token(token: str) -> bool:
    """True for a token shaped like BotFather issues it (no live check)."""
    return bool(_BOT_TOKEN_RE.fullmatch(token))


@dataclasses.dataclass(frozen=True)
class WebhookCreds:
    url: str
    secret: str | None


#: E.164: a leading +, a non-zero country digit, then 6 to 14 more digits.
_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def is_valid_phone(phone: str) -> bool:
    """True for an E.164 number CallMeBot will accept."""
    return bool(_PHONE_RE.fullmatch(phone))


#: CallMeBot issues an alphanumeric apikey with no fixed length; 4 is a floor
#: against an empty or single-character value, not a claim about the real one.
_APIKEY_RE = re.compile(r"^[0-9A-Za-z]{4,}$")


def is_valid_apikey(apikey: str) -> bool:
    """True for a CallMeBot apikey shape (no live check -- CallMeBot has none)."""
    return bool(_APIKEY_RE.fullmatch(apikey))


@dataclasses.dataclass(frozen=True)
class WhatsappCreds:
    phone: str
    apikey: str


@dataclasses.dataclass(frozen=True)
class AlertsChannels:
    telegram: TelegramCreds | None = None
    webhook: WebhookCreds | None = None
    whatsapp: WhatsappCreds | None = None


def _alerts_path() -> pathlib.Path:
    return get_settings().alerts_file


def _telegram_creds_from_dict(tg: dict) -> TelegramCreds:
    """Build TelegramCreds from a stored dict, either shape.

    Pre-1.1 files hold a single `"chat_id": "..."` string; 1.1+ files hold
    `"chat_ids": [...]`. Reading the old shape and turning it into a
    one-item tuple is the whole of the backward-compat contract here -- an
    upgraded install keeps sending to the same chat with no migration step
    and no data loss (an empty/missing value on either key becomes `()`,
    never a crash on a hand-edited file). `"chat_labels"` is newer still --
    missing entirely on any file written before it existed, and dropped
    rather than trusted if its length ever stops matching chat_ids (a
    hand-edited file, or one from a build that changed one but not the
    other).
    """
    tg = dict(tg)
    if "chat_ids" in tg:
        chat_ids = tg.pop("chat_ids")
    else:
        single = tg.pop("chat_id", "")
        chat_ids = [single] if single else []
    tg.pop("chat_id", None)  # a dict carrying both keys keeps chat_ids only
    chat_labels = tuple(tg.pop("chat_labels", None) or ())
    if len(chat_labels) != len(chat_ids):
        chat_labels = ()
    return TelegramCreds(chat_ids=tuple(chat_ids), chat_labels=chat_labels, **tg)


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
        wa = ch.get("whatsapp")
        return AlertsChannels(
            telegram=_telegram_creds_from_dict(tg) if tg else None,
            webhook=WebhookCreds(**wh) if wh else None,
            whatsapp=WhatsappCreds(**wa) if wa else None,
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
    if channels.whatsapp:
        data["channels"]["whatsapp"] = dataclasses.asdict(channels.whatsapp)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def mask_token(token: str) -> str:
    """First 4 + last 4 characters, else '***' for a token too short to mask safely."""
    return "***" if len(token) < 8 else token[:4] + "…" + token[-4:]


def mask_phone(phone: str) -> str:
    """Country code + last 2 digits, e.g. '+34…23'; '***' when too short to mask.

    Unlike mask_token's first-4/last-4 shape: a phone number's middle digits are
    the private part, and the country code alone identifies nobody.
    """
    digits = phone[1:] if phone.startswith("+") else phone
    return "***" if len(digits) < 4 else f"+{digits[:2]}…{digits[-2:]}"


def save_channel(**changes) -> None:
    """Replace named channels in alerts.json, leaving every other one alone.

    Each caller used to rebuild the whole AlertsChannels by hand, so adding a
    third channel meant editing eight call sites or silently wiping the new one
    from seven of them. dataclasses.replace makes that impossible.
    """
    save_alerts(dataclasses.replace(load_alerts(), **changes))

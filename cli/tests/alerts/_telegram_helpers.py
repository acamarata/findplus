"""Shared fakes for the Telegram channel test suite (test_telegram.py,
test_telegram_list_chats.py), split out so both stay under the PRI rule-7
300-line file cap without duplicating the same mock response builder.
"""

from __future__ import annotations

from unittest.mock import MagicMock

#: Shaped like a real BotFather token (digits, colon, 35-char secret) so it
#: passes store.is_valid_bot_token -- every test that exercises the real
#: send()/_get_me()/telegram_setup()/list_chats() must use a token this
#: shape now that all four reject a malformed one before making any request.
TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"


def _response(
    status_code: int, json_body: dict | None = None, text: str = "", headers: dict | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock()
    resp.headers = headers or {}
    return resp

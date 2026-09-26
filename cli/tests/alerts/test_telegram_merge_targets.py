"""alerts/channels/telegram.py: _handle_update()'s merge-on-reconnect (P14).

Split out of test_telegram.py (PRI rule-7 300-line cap) -- this file owns
only the "pressing Connect again" behaviour: merge into the existing target
list when the bot token is unchanged, replace when it changed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findplus.alerts.channels.telegram import telegram_setup
from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts

from ._telegram_helpers import TOKEN, _response

OTHER_TOKEN = "1111111111:ZYXwvuTSRqponMLKjihGFEdcbaZYXwvu0987"


def _existing(chat_ids: tuple[str, ...], chat_labels: tuple[str, ...] = (), token: str = TOKEN):
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token=token,
                chat_ids=chat_ids,
                chat_labels=chat_labels,
                chat_title="old",
                bot_username="oldbot",
                captured_at="then",
            )
        )
    )


def _connect(token: str, chat_id: int, chat_type: str = "private") -> None:
    update = {"update_id": 1, "message": {"chat": {"id": chat_id, "type": chat_type}}}
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = [
            _response(200, {"result": {"username": "testbot"}}),
            _response(200, {"result": [update]}),
        ]
        instance.post.return_value = _response(200)
        telegram_setup(token, wait_seconds=120, poll=2)


def test_reconnect_same_bot_merges_into_the_existing_list(tmp_db: str) -> None:
    _existing(("111", "222"), ("111", "@alice"))
    _connect(TOKEN, chat_id=333)

    from findplus.alerts.store import load_alerts

    tg = load_alerts().telegram
    assert tg.chat_ids == ("111", "222", "333")
    assert tg.chat_labels == ("111", "@alice", "private")


def test_reconnect_same_bot_refreshes_the_label_of_an_id_already_present(tmp_db: str) -> None:
    _existing(("111",), ("old-name",))
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 111, "type": "private", "username": "new_name"}},
    }
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = [
            _response(200, {"result": {"username": "testbot"}}),
            _response(200, {"result": [update]}),
        ]
        instance.post.return_value = _response(200)
        telegram_setup(TOKEN, wait_seconds=120, poll=2)

    from findplus.alerts.store import load_alerts

    tg = load_alerts().telegram
    assert tg.chat_ids == ("111",)
    assert tg.chat_labels == ("new_name",)


def test_reconnect_different_bot_token_replaces_the_list(tmp_db: str) -> None:
    _existing(("111", "222"), ("111", "222"), token=OTHER_TOKEN)
    _connect(TOKEN, chat_id=999)

    from findplus.alerts.store import load_alerts

    tg = load_alerts().telegram
    assert tg.chat_ids == ("999",)
    assert tg.bot_token == TOKEN


def test_merge_caps_at_max_targets_dropping_the_oldest(tmp_db: str) -> None:
    from findplus.alerts.targets import MAX_TARGETS

    ids = tuple(str(n) for n in range(MAX_TARGETS))
    _existing(ids, ids)
    _connect(TOKEN, chat_id=999999)

    from findplus.alerts.store import load_alerts

    tg = load_alerts().telegram
    assert len(tg.chat_ids) == MAX_TARGETS
    assert "0" not in tg.chat_ids  # oldest dropped
    assert "999999" in tg.chat_ids


def test_first_ever_connect_still_creates_a_single_target(tmp_db: str) -> None:
    save_mock = MagicMock()
    with patch("findplus.alerts.channels.telegram.save_channel", save_mock):
        _connect(TOKEN, chat_id=42)
    creds = save_mock.call_args.kwargs["telegram"]
    assert creds.chat_ids == ("42",)
    assert creds.chat_labels == ("private",)

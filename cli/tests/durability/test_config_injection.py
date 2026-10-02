"""A config value can never smuggle in another config.env line."""

from __future__ import annotations

import pytest

from findplus.config import (
    get_settings,
    reset_settings_cache,
    validate_config_key,
    write_config_key,
)
from findplus.config_keys import unprefixed_config_env

BAD = "/tmp/x\nRETENTION_DAYS=1\nPOLL_INTERVAL_MINUTES=0.5"


def test_patch_with_a_newline_is_refused_and_writes_nothing(client) -> None:
    res = client.patch("/api/settings", json={"backup.directory": BAD})
    assert res.status_code == 422
    env = get_settings().state_dir / "config.env"
    assert not env.exists() or "RETENTION_DAYS" not in env.read_text()
    reset_settings_cache()
    assert get_settings().effective_poll_interval_minutes >= 5


@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b", "a=b"])
def test_write_config_key_refuses_unsafe_values(tmp_db, bad) -> None:
    with pytest.raises(ValueError):
        write_config_key(get_settings(), "BACKUP_DIR", bad)
    with pytest.raises(ValueError):
        validate_config_key("backup_dir", bad)


def test_hand_edited_bad_values_are_ignored_on_read(tmp_db) -> None:
    state = get_settings().state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "config.env").write_text(
        "RETENTION_DAYS=1\nPOLL_INTERVAL_MINUTES=0.5\nLOG_LEVEL=DEBUG\n"
    )
    from findplus.config import Settings

    out = unprefixed_config_env(state, Settings.model_fields)
    assert "retention_days" not in out and "poll_interval_minutes" not in out
    assert out["log_level"] == "DEBUG"

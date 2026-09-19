"""Settings guardrails and log redaction."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from findplus.config import Settings
from findplus.logging_setup import _redact


# ------------------------------------------------------------------ binding
def test_default_bind_is_loopback_only() -> None:
    assert Settings().host == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.50", "::"])
def test_non_loopback_bind_is_refused(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """This app holds a child's location history; it must not reach the LAN by accident."""
    monkeypatch.delenv("FINDPLUS_ALLOW_PUBLIC_BIND", raising=False)
    with pytest.raises(ValueError, match="local-only by design"):
        Settings(host=host)


def test_public_bind_requires_an_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINDPLUS_ALLOW_PUBLIC_BIND", "1")
    assert Settings(host="0.0.0.0").host == "0.0.0.0"


# ------------------------------------------------------------------- limits
def test_poll_interval_must_be_positive() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        Settings(poll_interval_minutes=0)


def test_retention_zero_means_forever() -> None:
    assert Settings().retention_days == 0


def test_secrets_live_outside_the_repository() -> None:
    settings = Settings()
    from findplus.config import PROJECT_ROOT

    assert PROJECT_ROOT not in settings.secrets_file.parents


# --------------------------------------------------------------- redaction
@pytest.mark.parametrize(
    "key",
    [
        "password",
        "aas_token",
        "adm_token",
        "oauth_token",
        "cookie",
        "Authorization",
        "private_key",
        "owner_key",
        "identity_key",
        "fcm_credentials",
        "android_id",
        "api_key",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    out = _redact(None, "info", {key: "super-secret-value", "safe": "keep"})
    assert out[key] == "<redacted>"
    assert out["safe"] == "keep"


@pytest.mark.parametrize(
    "token",
    [
        "aas_et/AKppINZabcdefghijklmnop",
        "ya29.a0ARrdaM9abcdefghijklmn",
        "AIzaSyD_gko3P392v6how2H7Updx",
    ],
)
def test_token_shaped_strings_are_scrubbed_from_free_text(token: str) -> None:
    out = _redact(None, "info", {"event": f"request failed with {token} attached"})
    assert token not in out["event"]
    assert "<redacted>" in out["event"]


def test_ordinary_messages_survive_redaction() -> None:
    out = _redact(None, "info", {"event": "poll successful", "new_observations": 2})
    assert out["event"] == "poll successful"
    assert out["new_observations"] == 2


def test_logging_configuration_installs_handlers(tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings, reset_settings_cache
    from findplus.logging_setup import configure_logging

    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    reset_settings_cache()
    settings = get_settings()
    configure_logging(settings, to_file=True)
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
    assert settings.log_file.parent.exists()
    reset_settings_cache()


# ------------------------------------------------------------- state-dir paths
def test_default_database_under_home(tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    s = get_settings()
    assert s.database_path == tmp_path / ".findplus" / "findplus.sqlite"


def test_cwd_env_overrides(tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    (tmp_path / ".env").write_text("FINDPLUS_DATABASE_PATH=/custom/x.db\n")
    monkeypatch.chdir(tmp_path)
    s = get_settings()
    assert s.database_path == Path("/custom/x.db")


def test_env_var_overrides_both(tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "y.db"))
    s = get_settings()
    assert s.database_path == tmp_path / "y.db"


def test_state_dir_mode_0700(tmp_path) -> None:
    import stat

    from findplus.config import get_settings

    s = get_settings(state_dir=tmp_path / "sd")
    s.ensure_state_dir()
    assert stat.S_IMODE((tmp_path / "sd").stat().st_mode) == 0o700

"""The one validator `findplus config set` and PATCH /api/settings share.

Purpose    : specs/service-and-settings.md § 6 pins identical rules on both
             surfaces. Before P2 the CLI had its own private copy with a
             different poll-interval rule, so the two could disagree.
Inputs     : validate_config_key / write_config_key directly, plus one CliRunner
             call proving the CLI path reaches the same code.
Outputs    : none (assertions only).
Constraints: writes only into the tmp_db state dir; no network, no real HOME.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.config import get_settings, validate_config_key, write_config_key


# ------------------------------------------------------------------- host
def test_a_public_host_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINDPLUS_ALLOW_PUBLIC_BIND", raising=False)

    with pytest.raises(ValueError, match="Non-loopback host"):
        validate_config_key("HOST", "0.0.0.0")


def test_a_loopback_host_is_accepted() -> None:
    for host in ("127.0.0.1", "localhost", "::1"):
        validate_config_key("host", host)


def test_the_public_bind_opt_in_allows_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINDPLUS_ALLOW_PUBLIC_BIND", "1")

    validate_config_key("FINDPLUS_HOST", "0.0.0.0")


def test_a_falsy_opt_in_does_not_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """`=0` turning the guard OFF was E1's security round-3 F2; it stays off."""
    monkeypatch.setenv("FINDPLUS_ALLOW_PUBLIC_BIND", "0")

    with pytest.raises(ValueError, match="Non-loopback host"):
        validate_config_key("host", "0.0.0.0")


# ---------------------------------------------------------- poll interval
@pytest.mark.parametrize("value", ["5", "1440", "60"])
def test_poll_interval_inside_the_range_is_accepted(value: str) -> None:
    validate_config_key("poll_interval_minutes", value)


@pytest.mark.parametrize("value", ["4", "0", "1441", "2000"])
def test_poll_interval_outside_the_range_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="between 5 and 1440"):
        validate_config_key("POLL_INTERVAL_MINUTES", value)


def test_fast_polling_no_longer_loosens_the_shared_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 6 pins one rule for both surfaces, with no env carve-out."""
    monkeypatch.setenv("FINDPLUS_ALLOW_FAST_POLLING", "true")

    with pytest.raises(ValueError, match="between 5 and 1440"):
        validate_config_key("poll_interval_minutes", "1")


# -------------------------------------------------------------- retention
@pytest.mark.parametrize("value", ["0", "7", "30", "3650"])
def test_retention_zero_or_at_least_seven_is_accepted(value: str) -> None:
    validate_config_key("retention_days", value)


@pytest.mark.parametrize("value", ["1", "6", "-3"])
def test_retention_between_one_and_six_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="null \\(keep forever\\) or at least 7"):
        validate_config_key("RETENTION_DAYS", value)


def test_an_unknown_key_is_not_validated() -> None:
    validate_config_key("log_level", "anything at all")


# ------------------------------------------------------------------ write
def test_write_keeps_every_other_key(tmp_db) -> None:
    settings = get_settings()
    write_config_key(settings, "LOG_LEVEL", "DEBUG")
    write_config_key(settings, "RETENTION_DAYS", "30")

    write_config_key(settings, "POLL_INTERVAL_MINUTES", "15")

    text = (settings.state_dir / "config.env").read_text()
    assert "LOG_LEVEL=DEBUG" in text
    assert "RETENTION_DAYS=30" in text
    assert "POLL_INTERVAL_MINUTES=15" in text


def test_write_none_removes_the_key(tmp_db) -> None:
    settings = get_settings()
    write_config_key(settings, "LOG_LEVEL", "DEBUG")
    write_config_key(settings, "RETENTION_DAYS", "30")

    write_config_key(settings, "RETENTION_DAYS", None)

    text = (settings.state_dir / "config.env").read_text()
    assert "RETENTION_DAYS" not in text
    assert "LOG_LEVEL=DEBUG" in text


@pytest.mark.posix_only
def test_the_config_file_stays_owner_only(tmp_db) -> None:
    settings = get_settings()

    write_config_key(settings, "LOG_LEVEL", "DEBUG")

    assert (settings.state_dir / "config.env").stat().st_mode & 0o777 == 0o600


# -------------------------------------------------------------------- CLI
def test_cli_rejects_a_poll_interval_below_five(tmp_db) -> None:
    result = CliRunner().invoke(main, ["config", "set", "poll_interval_minutes", "3"])

    assert result.exit_code != 0
    assert "between 5 and 1440" in result.output


def test_cli_accepts_a_legal_poll_interval(tmp_db) -> None:
    result = CliRunner().invoke(main, ["config", "set", "poll_interval_minutes", "30"])

    assert result.exit_code == 0, result.output
    assert "POLL_INTERVAL_MINUTES=30" in (get_settings().state_dir / "config.env").read_text()

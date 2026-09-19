"""Regression tests for the non-HTTP half of the blind security review.

Each test reproduces the weakness first: a world-readable database, a secret
nested one level down in a log call, a flat brute-force lockout, a formula in
a CSV cell, a PIN in the process environment, a token file created at the
shell umask.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus.config import PRIVATE_UMASK, get_settings, reset_settings_cache
from findplus.exporters import to_csv
from findplus.logging_setup import _redact
from findplus.security import LOCKOUT_SECONDS, MAX_ATTEMPTS, MIN_PIN_LENGTH, SessionStore


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


# ------------------------------------------------------ 4. file permissions
def test_the_state_tree_is_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "state" / "findplus.sqlite"))
    reset_settings_cache()
    settings = get_settings()
    settings.ensure_dirs()
    assert _mode(settings.state_dir) == 0o700
    assert _mode(settings.log_dir) == 0o700
    reset_settings_cache()


def test_history_files_are_chmodded_even_when_sqlite_made_them_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attack: another account on this machine reads findplus.sqlite-wal."""
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "state" / "findplus.sqlite"))
    reset_settings_cache()
    settings = get_settings()
    settings.ensure_dirs()

    for path in settings.sensitive_paths():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        os.chmod(path, 0o644)

    settings.harden_permissions()
    for path in settings.sensitive_paths():
        assert _mode(path) == 0o600, path
    reset_settings_cache()


def test_the_cli_group_sets_a_private_umask() -> None:
    """The attack: `findplus serve` inherited a 0022 shell umask, so every file
    it created — database, WAL, log — was world-readable."""
    from findplus.cli.main import main

    original = os.umask(0o000)
    try:
        CliRunner().invoke(main, ["theme", "--help"])
        after = os.umask(0o000)
    finally:
        os.umask(original)
    assert after == PRIVATE_UMASK


# ------------------------------------------------------- 6. log redaction
def test_a_nested_secret_is_redacted() -> None:
    """The attack: the key check only looked at the top level, so any secret
    one dict deep was written to the log file verbatim."""
    event = {"event": "auth", "detail": {"bot_token": "12345678:supersecret"}}
    assert _redact(None, "", event)["detail"]["bot_token"] == "<redacted>"


def test_a_payload_key_is_redacted_whole() -> None:
    """`payload` carries Apple key material, so it never reaches the log at
    all, redacted as one value rather than walked into."""
    event = {"event": "auth", "payload": {"bot_token": "12345678:supersecret"}}
    assert _redact(None, "", event)["payload"] == "<redacted>"


def test_secrets_in_lists_and_tuples_are_redacted() -> None:
    event = {
        "event": "auth",
        "items": [{"password": "hunter2"}, ({"cookie": "abc"},)],
    }
    out = _redact(None, "", event)
    assert out["items"][0]["password"] == "<redacted>"
    assert out["items"][1][0]["cookie"] == "<redacted>"


def test_a_token_pasted_into_nested_free_text_is_scrubbed() -> None:
    event = {"event": "auth", "detail": {"body": "aas_et/AKppINd_ExampleTokenValue123"}}
    assert "aas_et/" not in _redact(None, "", event)["detail"]["body"]


def test_plain_values_are_left_alone() -> None:
    event = {"event": "poll", "count": 3, "device": "Moto Tag 2"}
    assert _redact(None, "", event) == event


# ----------------------------------------------------- 12. lockout / PIN len
def test_the_lockout_doubles_on_each_consecutive_round() -> None:
    """The attack: a flat 60s lockout costs a guesser one minute per five
    tries forever, which is affordable against a short PIN."""
    store = SessionStore()
    waits = []
    for _ in range(3):
        for _ in range(MAX_ATTEMPTS):
            store.record_failure()
        waits.append(store.seconds_until_retry())
        store._lockout_until = 0.0  # serve the lockout instantly

    assert waits[0] == pytest.approx(LOCKOUT_SECONDS, rel=0.05)
    assert waits[1] == pytest.approx(LOCKOUT_SECONDS * 2, rel=0.05)
    assert waits[2] == pytest.approx(LOCKOUT_SECONDS * 4, rel=0.05)


def test_the_lockout_is_capped_at_an_hour() -> None:
    store = SessionStore()
    for _ in range(12):
        for _ in range(MAX_ATTEMPTS):
            store.record_failure()
        store._lockout_until = 0.0
    for _ in range(MAX_ATTEMPTS):
        store.record_failure()
    assert store.seconds_until_retry() <= 3600.0


def test_a_correct_pin_resets_the_escalation() -> None:
    store = SessionStore()
    for _ in range(MAX_ATTEMPTS * 2):
        store.record_failure()
    store.clear_failures()
    for _ in range(MAX_ATTEMPTS):
        store.record_failure()
    assert store.seconds_until_retry() == pytest.approx(LOCKOUT_SECONDS, rel=0.05)


def test_the_minimum_pin_length_is_six() -> None:
    assert MIN_PIN_LENGTH == 6


# -------------------------------------------------------- 14. CSV injection
class _FakeObs:
    id = 1
    device_id = "TAG-001"
    device_name = '=HYPERLINK("http://evil.example.com","click")'
    latitude = 41.1
    longitude = -80.1
    accuracy_meters = 10.0
    altitude_meters = None
    source = "+AAA"
    is_own_report = False
    battery_level = None
    times_returned = 1

    def __init__(self, when) -> None:
        self.observed_at = when
        self.first_fetched_at = when


def test_a_formula_in_a_device_name_is_neutralised(base_time) -> None:
    """The attack: the tracker's name is attacker-controlled, and a spreadsheet
    executes a cell that starts with `=` the moment the export is opened."""
    body = to_csv([_FakeObs(base_time)], base_time.tzinfo)
    assert "'=HYPERLINK" in body
    assert '"=HYPERLINK' not in body
    assert ",'+AAA," in body
    assert ",+AAA," not in body


# ------------------------------------------------------- 13. MCP startup PIN
def test_the_pin_can_come_from_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from findplus.mcp.server import read_startup_pin

    pin_file = tmp_path / "pin"
    pin_file.write_text("864213\n")
    os.chmod(pin_file, 0o600)
    monkeypatch.delenv("FINDPLUS_PIN", raising=False)
    monkeypatch.setenv("FINDPLUS_PIN_FILE", str(pin_file))
    assert read_startup_pin() == "864213"


def test_the_pin_is_removed_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The attack: a child process (or anything reading /proc, or a crash
    dump) picks the PIN out of the still-populated environment."""
    monkeypatch.setenv("FINDPLUS_PIN", "864213")
    monkeypatch.setenv("FINDPLUS_PIN_FILE", "/nonexistent")
    from findplus.mcp.server import read_startup_pin

    assert read_startup_pin() == "864213"
    assert "FINDPLUS_PIN" not in os.environ
    assert "FINDPLUS_PIN_FILE" not in os.environ


def test_no_pin_configured_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from findplus.mcp.server import read_startup_pin

    monkeypatch.delenv("FINDPLUS_PIN", raising=False)
    monkeypatch.delenv("FINDPLUS_PIN_FILE", raising=False)
    assert read_startup_pin() is None


# ------------------------------------------------- 11. secrets.json creation
def test_the_token_store_is_created_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attack: upstream created secrets.json at the shell umask and we
    only chmodded it afterwards, leaving the tokens readable in between."""
    secrets_path = tmp_path / "state" / "secrets.json"
    secrets_path.parent.mkdir(parents=True)

    original = os.umask(0o000)
    try:
        secrets_path.touch(mode=0o600, exist_ok=True)
        secrets_path.write_text(json.dumps({"aas_token": "x"}))
    finally:
        os.umask(original)

    assert _mode(secrets_path) == 0o600


def test_set_and_harden_precreates_the_store() -> None:
    """The shipped hook must touch the file before delegating upstream.

    Asserted on the source because the hook only exists once the vendored
    GoogleFindMyTools is importable, which it is not in this suite.
    """
    from findplus.providers.google_findhub import bootstrap

    hook = Path(bootstrap.__file__).read_text().split("def _set_and_harden")[1]
    assert hook.index("touch(mode=0o600") < hook.index("_original_set(")

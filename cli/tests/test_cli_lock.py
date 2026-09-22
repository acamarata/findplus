"""`findplus lock reset` (UAT U20).

Purpose    : A third name for the existing `_clear_app_lock` recovery path
             (`reset-lock`, `pin reset`), added because the lock screen's
             forgotten-PIN hint now points to it by name.
Inputs     : CliRunner invocations against a tmp_db.
Outputs    : pytest assertions on exit code, console text and the stored PIN.
Constraints: Never touches the real ~/.findplus. `_clear_app_lock` itself had
             no prior test coverage (a UAT-found gap); this file also covers
             the shared no-PIN and confirm-declined branches through the new
             `lock reset` entry point.
"""

from __future__ import annotations

from click.testing import CliRunner

from findplus.appsettings import load_settings, save_pin
from findplus.cli.main import main
from findplus.db.session import session_scope
from findplus.security import hash_pin


def _set_a_pin() -> None:
    salt, digest = hash_pin("864213")
    with session_scope() as session:
        save_pin(session, salt, digest)


def test_lock_reset_with_no_pin_set_does_nothing(tmp_db) -> None:
    result = CliRunner().invoke(main, ["lock", "reset"])

    assert result.exit_code == 0, result.output
    assert "No PIN is set; nothing to reset." in result.output


def test_lock_reset_yes_clears_the_pin(tmp_db) -> None:
    _set_a_pin()

    result = CliRunner().invoke(main, ["lock", "reset", "--yes"])

    assert result.exit_code == 0, result.output
    assert "App lock removed" in result.output
    with session_scope() as session:
        settings = load_settings(session)
    assert settings.pin_configured is False
    assert settings.lock_enabled is False


def test_lock_reset_without_yes_prompts_and_aborts_on_no(tmp_db) -> None:
    _set_a_pin()

    result = CliRunner().invoke(main, ["lock", "reset"], input="n\n")

    assert result.exit_code != 0
    with session_scope() as session:
        assert load_settings(session).pin_configured is True


def test_lock_reset_without_yes_confirmed_clears_the_pin(tmp_db) -> None:
    _set_a_pin()

    result = CliRunner().invoke(main, ["lock", "reset"], input="y\n")

    assert result.exit_code == 0, result.output
    with session_scope() as session:
        assert load_settings(session).pin_configured is False

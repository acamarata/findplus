"""App lock: brute-force throttling and the filesystem-only PIN recovery path.

Split from test_lock_api.py (PRI rule 7, 449 lines); see _lock_helpers.py
for the shared client fixture and PIN.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus.security import MAX_ATTEMPTS
from tests.api._lock_helpers import PIN, _set_pin, client, store  # noqa: F401


def test_brute_force_is_throttled(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    for _ in range(MAX_ATTEMPTS):
        assert client.post("/api/lock/unlock", json={"pin": "000000"}).status_code == 401
    res = client.post("/api/lock/unlock", json={"pin": "000000"})
    assert res.status_code == 429
    assert "Try again in" in res.json()["detail"]


def test_throttling_blocks_even_the_correct_pin(client: TestClient) -> None:  # noqa: F811
    """Otherwise the lockout could be probed away by guessing."""
    _set_pin(client)
    client.cookies.clear()
    for _ in range(MAX_ATTEMPTS):
        client.post("/api/lock/unlock", json={"pin": "000000"})
    assert client.post("/api/lock/unlock", json={"pin": PIN}).status_code == 429


# ------------------------------------------------------- recovery from lockout
def test_reset_lock_cli_clears_a_forgotten_pin(client: TestClient) -> None:  # noqa: F811
    """The only PIN recovery path, and it requires local filesystem access."""
    from click.testing import CliRunner

    from findplus.appsettings import load_settings
    from findplus.cli.main import main
    from findplus.db.session import session_scope

    _set_pin(client)
    client.cookies.clear()
    assert client.get("/api/status").status_code == 401

    result = CliRunner().invoke(main, ["reset-lock", "--yes"])
    assert result.exit_code == 0, result.output

    with session_scope() as session:
        assert load_settings(session).pin_configured is False
    assert client.get("/api/status").status_code == 200


def test_reset_lock_is_harmless_when_no_pin_is_set(tmp_db) -> None:
    from click.testing import CliRunner

    from findplus.cli.main import main

    result = CliRunner().invoke(main, ["reset-lock", "--yes"])
    assert result.exit_code == 0
    assert "nothing to reset" in result.output.lower()

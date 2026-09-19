"""The watchdog restarts a wedged service but leaves a healthy one alone."""

from __future__ import annotations

import urllib.error

import pytest
from click.testing import CliRunner

from findplus.cli.main import main


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture
def restarts(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.restart_service", lambda: calls.append(True) or True)
    return calls


def _run(monkeypatch: pytest.MonkeyPatch, opener) -> str:
    monkeypatch.setattr("urllib.request.urlopen", opener)
    result = CliRunner().invoke(main, ["watchdog"])
    assert result.exit_code == 0, result.output
    return result.output


def test_healthy_service_is_left_alone(
    tmp_db, monkeypatch: pytest.MonkeyPatch, restarts: list[bool]
) -> None:
    _run(monkeypatch, lambda *a, **k: _Response(200))
    assert restarts == [], "a healthy service must never be restarted"


def test_locked_service_is_treated_as_healthy(
    tmp_db, monkeypatch: pytest.MonkeyPatch, restarts: list[bool]
) -> None:
    """401 means the app lock is on and the API is answering — not a failure."""

    def raise_401(*_a: object, **_k: object):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    _run(monkeypatch, raise_401)
    assert restarts == [], "the app lock must not trigger endless restarts"


def test_unreachable_service_is_restarted(
    tmp_db, monkeypatch: pytest.MonkeyPatch, restarts: list[bool]
) -> None:
    def refuse(*_a: object, **_k: object):
        raise ConnectionRefusedError("connection refused")

    output = _run(monkeypatch, refuse)
    assert restarts == [True]
    assert "restart requested" in output


def test_server_error_is_restarted(
    tmp_db, monkeypatch: pytest.MonkeyPatch, restarts: list[bool]
) -> None:
    def error_500(*_a: object, **_k: object):
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)

    _run(monkeypatch, error_500)
    assert restarts == [True]


def test_watchdog_never_raises(
    tmp_db, monkeypatch: pytest.MonkeyPatch, restarts: list[bool]
) -> None:
    """It runs unattended on a timer; a crash would be silent and permanent."""

    def explode(*_a: object, **_k: object):
        raise RuntimeError("something entirely unexpected")

    _run(monkeypatch, explode)
    assert restarts == [True]

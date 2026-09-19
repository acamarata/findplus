"""`findplus version` and `findplus version --check`."""

from __future__ import annotations

import importlib.metadata
import io
import json
import urllib.error

from click.testing import CliRunner

from findplus.cli.main import main


def test_version_prints() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert importlib.metadata.version("findplus") in result.output


def test_check_update_available(monkeypatch) -> None:
    payload = json.dumps({"tag_name": "v99.99.99"}).encode()

    def _fake_urlopen(request, timeout=10):
        return io.BytesIO(payload)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    runner = CliRunner()
    result = runner.invoke(main, ["version", "--check"])
    assert result.exit_code == 0
    assert "Update available: v99.99.99" in result.output


def test_check_up_to_date(monkeypatch) -> None:
    current = importlib.metadata.version("findplus")
    payload = json.dumps({"tag_name": f"v{current}"}).encode()

    def _fake_urlopen(request, timeout=10):
        return io.BytesIO(payload)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    runner = CliRunner()
    result = runner.invoke(main, ["version", "--check"])
    assert result.exit_code == 0
    assert "Up to date." in result.output


def test_check_network_error(monkeypatch) -> None:
    def _fake_urlopen(request, timeout=10):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    runner = CliRunner()
    result = runner.invoke(main, ["version", "--check"])
    assert result.exit_code == 0
    assert "Could not check for updates" in result.output

"""`findplus version` and `findplus version --check`."""

from __future__ import annotations

import importlib.metadata
import io
import json
import urllib.error

import pytest
from click.testing import CliRunner

from findplus.cli.cmd_version import _RELEASES_URL
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


def _patch_urlopen(monkeypatch, payload: bytes):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=10: io.BytesIO(payload))


@pytest.mark.parametrize(
    "payload",
    [
        b"<html>rate limited</html>",  # not JSON at all
        b"{}",  # JSON, but no tag_name
        b'{"tag_name": null}',  # tag_name present and unusable
    ],
    ids=["not-json", "no-tag-name", "null-tag-name"],
)
def test_check_malformed_release_json(monkeypatch, payload: bytes) -> None:
    """A bad response from GitHub prints one stderr line and still exits 0."""
    _patch_urlopen(monkeypatch, payload)
    result = CliRunner().invoke(main, ["version", "--check"])
    assert result.exit_code == 0
    assert "Could not check for updates" in result.output
    assert "Traceback" not in result.output


def test_check_http_error(monkeypatch) -> None:
    def _raise(request, timeout=10):
        raise urllib.error.HTTPError(_RELEASES_URL, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    result = CliRunner().invoke(main, ["version", "--check"])
    assert result.exit_code == 0
    assert "Could not check for updates" in result.output


def test_check_uses_the_pinned_github_releases_url(monkeypatch) -> None:
    """cli-reference.md § version: one GET to the GitHub releases API, with a timeout."""
    seen = {}

    def _capture(request, timeout=None):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return io.BytesIO(json.dumps({"tag_name": "v0.0.1"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", _capture)
    assert CliRunner().invoke(main, ["version", "--check"]).exit_code == 0
    assert seen["url"] == _RELEASES_URL
    assert seen["timeout"] == 10

"""Google sign-in drives Google Chrome, never a Chromium that happens to be on PATH.

undetected_chromedriver's own finder takes the first existing entry of a *set*
of PATH names and app paths, so with Homebrew's `chromium` wrapper on PATH it
picked that wrapper about half the time and the sign-in failed with "chrome not
reachable". chrome_path.chrome_kwargs() pins Google Chrome instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from findplus.providers.google_findhub import chrome_path

from .test_google_browser_auth import FakeDriver, _patched_create_driver


def _fake_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    return path


def test_mac_prefers_the_google_chrome_app(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    chrome = _fake_binary(home / "Applications" / chrome_path._MAC_APP)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # A chromium on PATH must not matter on macOS: only the app paths count.
    monkeypatch.setattr(chrome_path.shutil, "which", lambda name: "/opt/homebrew/bin/chromium")
    real_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: False if str(self).startswith("/Applications/") else real_is_file(self),
    )

    assert chrome_path.find_google_chrome() == str(chrome)
    assert chrome_path.chrome_kwargs() == {"browser_executable_path": str(chrome)}


def test_linux_ignores_chromium_and_finds_google_chrome(tmp_path, monkeypatch) -> None:
    chrome = _fake_binary(tmp_path / "bin" / "google-chrome")
    monkeypatch.setattr(sys, "platform", "linux")
    names = {"google-chrome": str(chrome), "chromium": str(tmp_path / "bin" / "chromium")}
    monkeypatch.setattr(chrome_path.shutil, "which", lambda name: names.get(name))

    assert chrome_path.find_google_chrome() == str(chrome)


def test_no_google_chrome_leaves_the_choice_to_undetected_chromedriver(monkeypatch) -> None:
    monkeypatch.setattr(chrome_path, "_candidates", lambda: [None, "/nonexistent/chrome"])

    assert chrome_path.find_google_chrome() is None
    assert chrome_path.chrome_kwargs() == {}


@pytest.mark.posix_only
def test_create_driver_passes_the_google_chrome_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        chrome_path, "chrome_kwargs", lambda: {"browser_executable_path": "/x/Google Chrome"}
    )
    made: list[FakeDriver] = []
    create_driver, _settings = _patched_create_driver(tmp_path, monkeypatch, made)

    create_driver()

    assert made[0].kwargs["browser_executable_path"] == "/x/Google Chrome"

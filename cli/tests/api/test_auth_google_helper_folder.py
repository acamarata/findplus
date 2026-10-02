"""POST /api/auth/google/helper/folder: copy the helper, return its path, open nothing.

Purpose    : The 1.2 install steps show the helper folder as copyable text. The
             route must copy the helper into the state dir and answer {path},
             refuse without same-origin proof, 401 while the app is locked, and
             never start a program (Finder, Chrome, a browser), even with the
             launch guard switched off.
"""

from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path

import pytest

from tests.api._auth_helpers import SAME_ORIGIN_HEADERS

FOLDER = "/api/auth/google/helper/folder"


@pytest.fixture
def launches(monkeypatch, launch_allowed) -> list[str]:
    """Guard off, every launcher recorded instead of run."""
    seen: list[str] = []

    def record(name):
        def _fake(*args, **kwargs):
            seen.append(name)
            raise AssertionError(f"{name} must not run")

        return _fake

    monkeypatch.setattr(subprocess, "Popen", record("Popen"))
    monkeypatch.setattr(subprocess, "run", record("run"))
    monkeypatch.setattr(webbrowser, "open", record("webbrowser.open"))
    return seen


def test_folder_copies_the_helper_and_returns_its_path(auth_client, launches) -> None:
    from findplus.config import get_settings

    res = auth_client.post(FOLDER, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 200, res.text
    path = Path(res.json()["path"])
    assert path.is_relative_to(Path(get_settings().state_dir) / "chrome-helper")
    assert (path / "manifest.json").is_file()
    assert launches == []


def test_folder_twice_is_fine_and_still_opens_nothing(auth_client, launches) -> None:
    first = auth_client.post(FOLDER, headers=SAME_ORIGIN_HEADERS).json()["path"]
    second = auth_client.post(FOLDER, headers=SAME_ORIGIN_HEADERS).json()["path"]
    assert first == second
    assert launches == []


def test_folder_never_calls_the_reveal_or_extensions_openers(auth_client, monkeypatch) -> None:
    from findplus.providers.google_findhub import browser_helper

    def boom(*_a, **_k):
        raise AssertionError("the folder route must not reveal or open anything")

    monkeypatch.setattr(browser_helper, "reveal_helper", boom)
    monkeypatch.setattr(browser_helper, "open_chrome_extensions", boom)
    assert auth_client.post(FOLDER, headers=SAME_ORIGIN_HEADERS).status_code == 200


def test_folder_needs_same_origin_proof(auth_client) -> None:
    assert auth_client.post(FOLDER).status_code == 403


def test_folder_is_401_while_locked(locked_client) -> None:
    assert locked_client.post(FOLDER, headers=SAME_ORIGIN_HEADERS).status_code == 401


def test_folder_reports_missing_helper_files_plainly(auth_client, monkeypatch) -> None:
    from findplus.providers.google_findhub import browser_helper

    monkeypatch.setattr(browser_helper, "helper_available", lambda: (False, "files not found"))
    res = auth_client.post(FOLDER, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 503
    assert res.json()["detail"] == "files not found"


def test_the_begin_page_gives_text_steps_not_a_button(auth_client) -> None:
    body = auth_client.get("/auth/google/begin?state=abc").text
    assert "Show helper folder" not in body
    assert "<code>chrome://extensions</code>" in body
    assert "Load unpacked" in body and "Copy button" in body

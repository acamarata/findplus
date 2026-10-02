"""Locating, installing and revealing the shipped Chrome helper (no real launch)."""

from __future__ import annotations

import json
import os
import stat

import pytest

from findplus.providers.google_findhub import browser_helper as bh


def test_the_helper_ships_and_is_found_in_the_dev_tree() -> None:
    available, reason = bh.helper_available()
    assert available is True, reason
    assert (bh.packaged_helper_dir() / "manifest.json").is_file()
    assert bh.helper_version() == "1.1.5"


def _fake_source(tmp_path):
    src = tmp_path / "shipped"
    src.mkdir(exist_ok=True)
    (src / "manifest.json").write_text(json.dumps({"version": "1.1.5"}))
    (src / "background.js").write_text("// worker")
    return src


def test_install_copies_the_extension_into_the_state_dir(tmp_db, tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    monkeypatch.setattr(bh, "packaged_helper_dir", lambda: _fake_source(tmp_path))
    dest = bh.install_helper(get_settings())
    assert dest.name == "1.1.5"
    assert (dest / "manifest.json").is_file()
    assert (dest / "background.js").is_file()


@pytest.mark.posix_only
def test_install_makes_a_private_parent(tmp_db, tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    monkeypatch.setattr(bh, "packaged_helper_dir", lambda: _fake_source(tmp_path))
    dest = bh.install_helper(get_settings())
    assert stat.S_IMODE(os.stat(dest.parent).st_mode) == 0o700


@pytest.mark.usefixtures("launch_allowed")
def test_reveal_opens_the_file_manager(tmp_db, tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    monkeypatch.setattr(bh, "packaged_helper_dir", lambda: _fake_source(tmp_path))
    calls = []
    monkeypatch.setattr(bh.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(bh.sys, "platform", "darwin")
    dest = bh.reveal_helper(get_settings())
    assert calls == [["open", str(dest)]]


def test_install_without_files_raises(tmp_db, tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    monkeypatch.setattr(bh, "packaged_helper_dir", lambda: tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        bh.install_helper(get_settings())


@pytest.mark.usefixtures("launch_allowed")
def test_open_chrome_extensions_on_macos(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(bh.sys, "platform", "darwin")
    monkeypatch.setattr(bh.subprocess, "run", lambda argv, **kw: calls.append(argv))
    assert bh.open_chrome_extensions() is True
    assert calls == [["open", "-a", "Google Chrome", "chrome://extensions"]]


@pytest.mark.usefixtures("launch_allowed")
def test_open_chrome_extensions_without_chrome_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(bh.sys, "platform", "linux")
    monkeypatch.setattr(
        "findplus.providers.google_findhub.chrome_path.find_google_chrome", lambda: None
    )
    spawned = []
    monkeypatch.setattr(bh.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    assert bh.open_chrome_extensions() is False
    assert spawned == []

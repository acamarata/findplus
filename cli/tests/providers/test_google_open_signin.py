"""open_signin.py: Google's sign-in page opens in the user's own Chrome.

Purpose    : The argv per platform (macOS `open -a "Google Chrome"`, the Chrome
             binary on Windows/Linux, always a list), the default-browser
             fallback, and a plain error when nothing opens.
Constraints: No browser is ever launched. `_launch_chrome` is imported here at
             module load, before the autouse no_real_browser guard replaces it
             on the module, and every call it makes goes to a patched
             subprocess.
"""

from __future__ import annotations

import subprocess

import pytest

from findplus.providers.google_findhub import open_signin
from findplus.providers.google_findhub.open_signin import _launch_chrome as real_launch

URL = open_signin.EMBEDDED_SETUP_URL
CHROME = "/opt/google/chrome/chrome"


def test_macos_hands_the_url_to_the_running_chrome(monkeypatch) -> None:
    monkeypatch.setattr(open_signin.sys, "platform", "darwin")
    assert open_signin.chrome_argv("/Applications/x", URL) == ["open", "-a", "Google Chrome", URL]


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_windows_and_linux_launch_the_found_binary(monkeypatch, platform) -> None:
    monkeypatch.setattr(open_signin.sys, "platform", platform)
    assert open_signin.chrome_argv(CHROME, URL) == [CHROME, URL]


@pytest.mark.usefixtures("launch_allowed")
def test_macos_runs_open_and_waits_for_it(monkeypatch) -> None:
    runs: list[list[str]] = []
    monkeypatch.setattr(open_signin.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: runs.append(argv))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no Popen on macOS"))
    assert real_launch("/Applications/x", URL) is True
    assert runs == [["open", "-a", "Google Chrome", URL]]


@pytest.mark.usefixtures("launch_allowed")
def test_linux_detaches_the_browser(monkeypatch) -> None:
    spawned: list[tuple] = []
    monkeypatch.setattr(open_signin.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: spawned.append((argv, kw)))
    assert real_launch(CHROME, URL) is True
    argv, kwargs = spawned[0]
    assert argv == [CHROME, URL]
    assert kwargs["start_new_session"] is True
    assert "shell" not in kwargs


@pytest.mark.usefixtures("launch_allowed")
def test_a_failed_launch_reports_false(monkeypatch) -> None:
    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(open_signin.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", fail)
    assert real_launch("/Applications/x", URL) is False


def test_chrome_is_used_when_found(monkeypatch, no_real_browser) -> None:
    monkeypatch.setattr(open_signin, "find_google_chrome", lambda: CHROME)
    assert open_signin.open_sign_in_page() == "chrome"
    assert no_real_browser == [URL]


@pytest.mark.usefixtures("launch_allowed")
def test_without_chrome_the_default_browser_opens_the_page(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(open_signin, "find_google_chrome", lambda: None)
    monkeypatch.setattr(open_signin.webbrowser, "open", lambda url: opened.append(url) or True)
    assert open_signin.open_sign_in_page() == "default"
    assert opened == [URL]


def test_a_chrome_that_fails_to_open_falls_back_to_the_default(monkeypatch) -> None:
    monkeypatch.setattr(open_signin, "find_google_chrome", lambda: CHROME)
    monkeypatch.setattr(open_signin, "_launch_chrome", lambda chrome, url: False)
    monkeypatch.setattr(open_signin.webbrowser, "open", lambda url: True)
    assert open_signin.open_sign_in_page() == "default"


@pytest.mark.usefixtures("launch_allowed")
def test_nothing_opening_is_a_plain_error(monkeypatch) -> None:
    monkeypatch.setattr(open_signin, "find_google_chrome", lambda: None)
    monkeypatch.setattr(open_signin.webbrowser, "open", lambda url: False)
    with pytest.raises(open_signin.BrowserOpenError, match="could not open a browser"):
        open_signin.open_sign_in_page()

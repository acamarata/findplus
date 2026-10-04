"""Autouse guard: no test ever opens a real browser on the machine running it.

Purpose    : `POST /api/auth/google/open` really opens Google Chrome (macOS
             `open -a`, or the Chrome binary) and falls back to
             `webbrowser.open`. Route sweeps (test_origin_guard_sweep.py) POST
             to every mutating route, so without this guard a test run would
             open the owner's own Chrome, which touches their keychain. Both
             launch paths in open_signin.py are replaced with a recorder that
             answers "opened", so sweeps still see a normal response.
Outputs    : The `no_real_browser` list of URLs a test "opened".
Constraints: Imported into cli/tests/conftest.py so it applies to every test.
             Tests that assert on argv patch `_launch_chrome`/`subprocess`
             themselves, on top of this.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from findplus.providers.google_findhub import open_signin

    opened: list[str] = []

    def _record(*args, **kwargs) -> bool:
        opened.append(str(args[-1]) if args else "")
        return True

    # Pretend Chrome is installed (a CI box has none); a test that wants "no Chrome"
    # patches find_google_chrome back to None itself.
    monkeypatch.setattr(open_signin, "find_google_chrome", lambda: "/x/chrome")
    monkeypatch.setattr(open_signin, "_launch_chrome", _record)
    monkeypatch.setattr(open_signin.webbrowser, "open", _record)
    return opened

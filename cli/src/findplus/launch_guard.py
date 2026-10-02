"""One switch that stops Find+ from launching anything on the machine it runs on.

Purpose    : Several actions open a real program: the sign-in page in Chrome, the
             helper's folder in Finder, chrome://extensions, the dashboard in a
             browser, the app. Tests, fixture servers and screenshot scripts must
             never do that to a person's computer (it also touches their keychain
             and logins).
Outputs    : `launching_disabled()`: True when FINDPLUS_NO_LAUNCH is set or when
             running under pytest. Every launcher checks it first and answers as
             if the launch worked.
Constraints: A static test (tests/test_no_real_launch.py) fails when a module that
             can launch a program does not call this.
"""

from __future__ import annotations

import os

#: A test that mocks the launch call itself (and asserts on its arguments) may
#: switch the guard off for that one test; see the `launch_allowed` fixture.
_allow_for_mocked_test = False


def launching_disabled() -> bool:
    """True when nothing may be opened on this machine (tests, fixtures, scripts)."""
    if _allow_for_mocked_test:
        return False
    return bool(os.environ.get("FINDPLUS_NO_LAUNCH") or os.environ.get("PYTEST_CURRENT_TEST"))

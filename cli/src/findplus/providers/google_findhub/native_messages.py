"""Plain-words text for the in-app Google sign-in window's card and CLI.

Purpose    : One copy of every sentence the daemon reports for the in-app
             sign-in flow (native_flow.py), so the dashboard card, `findplus
             auth --status` and the desktop shell all say the same thing.
Inputs     : None.
Outputs    : MSG_* constants and the PHASE_MESSAGES map (phase -> sentence).
Constraints: Written for a person: no "cookie", no "token", no em dashes. Never
             carries a token, a key or page contents. The honesty sentence about
             in-app sign-in lives in honesty.py (NATIVE_SIGNIN), not here.
"""

from __future__ import annotations

MSG_IDLE = ""
MSG_CONNECTING = "Opening the sign-in window..."
MSG_WAITING = "Finish signing in in the Find+ window."
MSG_FINISHING = "Checking with Google..."
MSG_GOOGLE_SLOW = "Google is slow to answer. Trying again..."
MSG_GOOGLE_UNREACHABLE = "Couldn't reach Google. Check your internet connection and try again."
MSG_NEEDS_UNLOCK = "One more step: enter your Android phone's screen lock in the same window."
MSG_UNLOCK_WAITING = "Unlock your locations in the Find+ window."
MSG_SIGNED_IN = "Connected as {account}."
MSG_UNLOCKED = "Connected as {account}. Locations unlocked."
MSG_CANCELLED = "Cancelled. Nothing changed."

MSG_BLOCKED = "Google would not let Find+ sign you in inside the app. Use your Chrome instead."
MSG_OUTSIDE_GOOGLE = (
    "This account signs in on another company's page, which the Find+ window does not "
    "open. Use your Chrome instead."
)
MSG_STUCK = "The sign-in window stopped moving. Use your Chrome instead, or try again."

MSG_WINDOW_OPEN = "The Find+ sign-in window is already open."
MSG_STATE_GONE = "This sign-in expired or was already used. Start it again from Find+."
MSG_NOT_SIGNED_IN = "Sign in to Google first, then unlock your locations."
MSG_UNLOCK_UNAVAILABLE = "Find+ could not prepare the unlock page. Try again in a moment."
MSG_ACCOUNT_MISMATCH = (
    "The unlock page is signed in to a different Google account than Find+. Unlock with {account}."
)
MSG_ACCOUNT_UNKNOWN = (
    "Find+ could not tell which Google account the window is signed in to, so it saved "
    "nothing. Try again."
)
MSG_LOAD_FAILED = "The sign-in page did not load. Check your internet connection and try again."
MSG_WINDOW_FAILED = (
    "Find+ could not finish the sign-in in its window. Try again, or use your Chrome."
)
MSG_TIMED_OUT = "The sign-in window was open too long and closed. Start again when you are ready."
MSG_HANDOFF_FAILED = "Find+ could not finish the sign-in. Start it again from Find+."

#: Plain words for each `reason` the shell may send with `event: failed`.
FAILED_REASONS: dict[str, str] = {
    "load_failed": MSG_LOAD_FAILED,
    "timeout": MSG_TIMED_OUT,
    "cookie_read_failed": MSG_WINDOW_FAILED,
    "bridge_bad": MSG_WINDOW_FAILED,
    "account_unknown": MSG_ACCOUNT_UNKNOWN,
    "google_unreachable": MSG_GOOGLE_UNREACHABLE,
    "other": MSG_WINDOW_FAILED,
}

#: Plain words for each `reason` a blocked window carries.
BLOCKED_REASONS: dict[str, str] = {
    "rejected_page": MSG_BLOCKED,
    "disallowed_useragent": MSG_BLOCKED,
    "outside_google": MSG_OUTSIDE_GOOGLE,
    "stuck": MSG_STUCK,
    "other": MSG_BLOCKED,
}

#: Google answered but issued nothing for this sign-in (the window's own words;
#: token_signin.MSG_REJECTED talks about copying, which the window never asks for).
MSG_REJECTED = "Google did not accept this sign-in. Try again in the Find+ window."

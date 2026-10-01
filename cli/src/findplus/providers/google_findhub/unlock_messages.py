"""User-facing sentences for the Google unlock job (split from unlock.py, 300-line cap)."""

from __future__ import annotations

MSG_LAUNCHING = "Starting the Find+ Chrome window..."
MSG_WAITING = (
    "In the Find+ Chrome window, sign in with the same Google account first if Google asks, "
    "then enter your Android phone's screen lock."
)
MSG_SAVING = "Saving the key..."
MSG_DONE = "Encrypted locations unlocked."
MSG_DONE_UNVERIFIED = (
    "Encrypted locations unlocked, but Find+ could not confirm which Google account the window "
    "used. If locations still do not show, unlock again signed in as the account Find+ uses."
)
MSG_CANCELLED = "Unlock cancelled."
MSG_FAILED = "The unlock did not finish. Try again."
MSG_TIMEOUT = "The unlock window was open too long. Start the unlock again."
MSG_NOT_SIGNED_IN = "Find+ is not signed in to Google. Sign in first, then unlock."
MSG_NO_KEY = "That page did not return an encryption key. Try again."
MSG_NO_VAULT_KEY = (
    "No usable encryption key was found. Enter your Android screen lock and try again."
)

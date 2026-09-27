"""`findplus auth --unlock`: unlock a Google account's encrypted locations.

Purpose    : CLI parity with the dashboard's "Unlock encrypted locations" step.
             Google encrypts Find Hub locations end to end and releases the key
             only to a browser page that has passed the account's Android
             screen-lock check, so Find+ opens a Chrome window of its own and
             the user completes their phone's screen lock in it. Find+ pastes
             nothing and shows no console snippet.
Inputs     : none; the job opens the window and waits.
Outputs    : the stored `shared_key` (0600, via the vendored store); console
             progress here. Never prints the key.
Constraints: Runs the same job the API uses (providers/google_findhub/unlock.py)
             and polls it, so the two surfaces cannot drift. Ctrl-C cancels the
             job (closing the window) rather than leaving it running. Split out
             of cmd_auth.py to keep that file under the 300-line cap.
"""

from __future__ import annotations

import sys
import time

import click

POLL_SECONDS = 1.0
_TERMINAL = ("done", "failed")


def _needs_unlock(settings) -> bool:
    from findplus.providers.google_findhub.bootstrap import (
        has_google_session,
        needs_shared_key,
    )

    if not has_google_session():
        click.secho("Sign in to Google first: findplus auth", fg="red", err=True)
        return False
    if not needs_shared_key():
        click.secho("Encrypted locations are already unlocked.", fg="green")
        return False
    return True


def _explain() -> None:
    click.echo("")
    click.secho("Unlock encrypted locations", bold=True)
    click.echo(
        "Google encrypts your Find Hub locations end to end. Unlocking them needs\n"
        "your Android phone's screen lock, once. Find+ opens a Chrome window of its\n"
        "own for this, because Google releases the key only to a browser page. Do\n"
        "the screen-lock prompt in that window. Find+ never asks you to paste code.\n"
    )


def auth_google_unlock(settings) -> None:
    """Start the unlock job, follow it to the end, exit 1 on failure."""
    if not _needs_unlock(settings):
        return
    _explain()
    if not click.confirm("Open the Find+ Chrome window now?", default=True):
        raise click.Abort

    from findplus.providers.google_findhub.unlock import (
        cancel_google_unlock,
        get_google_unlock_progress,
        start_google_unlock,
    )

    job_id = start_google_unlock(settings)
    last = None
    try:
        while True:
            time.sleep(POLL_SECONDS)
            progress = get_google_unlock_progress(job_id)
            if progress is None:
                click.secho("The unlock expired. Try again.", fg="red", err=True)
                sys.exit(1)
            if progress["message"] != last:
                click.echo(progress["message"])
                last = progress["message"]
            if progress["state"] in _TERMINAL:
                break
    except KeyboardInterrupt:
        cancel_google_unlock(job_id)
        click.echo("\nUnlock cancelled.")
        sys.exit(1)

    if progress["state"] == "done":
        click.secho("\nEncrypted locations unlocked.", fg="green")
        click.echo("Next: findplus poll-now")
    else:
        click.secho(f"\n{progress['message']}", fg="red", err=True)
        sys.exit(1)

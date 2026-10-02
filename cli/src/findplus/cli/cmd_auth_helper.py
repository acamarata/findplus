"""`findplus auth` through the Find+ helper: the same route the dashboard leads with.

Purpose    : CLI parity with the dashboard's "Sign in with Google" button. The
             running daemon opens its 127.0.0.1 begin page in the user's own
             Chrome; the Find+ helper hands the sign-in token back to the daemon;
             this command just waits for the daemon to report it. It prints the
             begin address first so a headless or remote shell can open it by
             hand. The separate Chrome window stays the fallback.
Inputs     : the settings (daemon port); the user's yes/no.
Outputs    : the signed-in account via the daemon (secrets.json 0600); console
             lines only here. The token never passes through this process.
Constraints: Needs the daemon running (it holds the single-use state). Returns
             False, printing why, whenever the helper route is unavailable or did
             not finish, so the caller falls through to the old flow. Same
             honesty rules as the dashboard: the helper needs Google Chrome.
"""

from __future__ import annotations

import time

import click
import httpx

POLL_SECONDS = 2.0
WAIT_SECONDS = 300.0
PROVIDER_ID = "google-find-hub"


def _headers(base: str) -> dict[str, str]:
    # The same-origin proof the dashboard's own fetch sends (routes that start a
    # sign-in refuse a request with neither header).
    return {"Origin": base, "Sec-Fetch-Site": "same-origin"}


def _daemon_status(base: str) -> dict | None:
    """The auth status from the running daemon, or None (down, locked, foreign)."""
    try:
        res = httpx.get(f"{base}/api/auth/status", timeout=3.0)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def _fail(message: str) -> None:
    click.secho(message, fg="red", err=True)


def _begin(base: str) -> dict | None:
    prefix = "Find+ could not start the helper sign-in"
    try:
        res = httpx.post(
            f"{base}/api/auth/google/helper/begin", headers=_headers(base), timeout=10.0
        )
        if res.status_code == 202:
            return res.json()
        _fail(f"{prefix}: {res.json().get('detail', res.status_code)}")
    except Exception as exc:
        _fail(f"{prefix}: {exc}")
    return None


def _landed(status: dict, baseline: int) -> tuple[bool, str]:
    """(a sign-in newer than `baseline` landed, its account or "")."""
    if int(status.get("google_signin_generation") or 0) <= baseline:
        return False, ""
    google = next((p for p in status.get("providers", []) if p["id"] == PROVIDER_ID), None)
    return True, (google or {}).get("account") or ""


def _failed_outcome(status: dict) -> str | None:
    outcome = status.get("google_helper_outcome")
    if outcome and outcome.get("ok") is False and outcome.get("kind") == "signin":
        return outcome.get("message") or "The sign-in did not finish."
    return None


def _wait(base: str, baseline: int) -> tuple[bool, str]:
    """(finished, account). Not finished on a reported failure or the 5-minute limit."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        status = _daemon_status(base)
        if status is None:
            continue
        failure = _failed_outcome(status)
        if failure:
            _fail(failure)
            return False, ""
        landed, account = _landed(status, baseline)
        if landed:
            return True, account
    _fail("The sign-in did not finish in 5 minutes. Is the Find+ helper added to Chrome?")
    return False, ""


def _explain(url: str, helper_seen: bool) -> None:
    click.echo("")
    click.secho("Google sign-in with the Find+ helper", bold=True)
    click.echo(
        "Find+ opens Google's sign-in page in your own Google Chrome. The Find+ helper\n"
        "(a small Chrome extension) passes the sign-in to Find+ on this computer. You\n"
        "type your password on Google's own page; Find+ never sees it.\n"
    )
    if not helper_seen:
        click.echo(
            "The helper has not been seen yet. First time: in the Find+ dashboard open\n"
            "Settings > Sign-in > First time? and add it to Chrome (one time).\n"
        )
    click.echo(f"If Chrome did not open, open this address in Chrome:\n  {url}\n")


def auth_google_helper(settings) -> bool:
    """Offer and run the helper route. True when signed in; False to fall back."""
    base = f"http://127.0.0.1:{settings.port}"
    status = _daemon_status(base)
    if status is None:
        click.echo(
            "The helper sign-in needs the Find+ service running and unlocked; using the other way."
        )
        return False
    seen = bool(status.get("google_helper_installed"))
    if not click.confirm("Sign in through the Find+ helper in your own Chrome?", default=seen):
        return False
    begun = _begin(base)
    if begun is None:
        return False
    _explain(str(begun.get("url", "")), seen)
    finished, account = _wait(base, int(begun.get("generation") or 0))
    if not finished:
        return False
    click.secho(f"\nAuthenticated{f' as {account}' if account else ''}.", fg="green")
    click.echo("Next: findplus devices")
    return True

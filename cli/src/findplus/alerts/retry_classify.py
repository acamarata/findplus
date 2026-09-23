"""Retry classification and backoff scheduling for alert deliveries.

Purpose : Decide whether a failed delivery is worth retrying, and when the
          next attempt is due. Split out of dispatch_core.py (PRI hard rule
          7: <=300 lines/file) -- pure, no DB or network import, same as the
          rest of dispatch_core.
Inputs  : A channel's send outcome (status/error/status_code/retry_after).
Outputs : is_transient_failure() a bool; compute_next_attempt_at() a
          datetime; classify_new_delivery() the (status, attempts,
          next_attempt_at) tuple written for a first-time delivery row.
Constraints: Re-exported by dispatch_core.py so every existing
          `from findplus.alerts.dispatch_core import ...` call site is
          unchanged.
"""

from __future__ import annotations

import datetime

#: Minutes after the first failure that retry 1/2/3 (attempts 2/3/4) are due.
#: Indexed by `attempts - 1`, where `attempts` is the count already made.
RETRY_OFFSETS_MINUTES = (1, 5, 30)

#: 1 initial send + 3 retries. `attempts` reaching this with no success means
#: give up -- the row's final status is "failed", not "retrying" again.
MAX_ATTEMPTS = 4

_RETRY_CAP = datetime.timedelta(minutes=RETRY_OFFSETS_MINUTES[-1])


#: Every error a channel produces with no HTTP status that is NOT a network
#: condition -- a credential/shape problem the channel validated before ever
#: opening a connection. Exact-text match, not a substring: a genuine network
#: failure (connection refused/reset, DNS failure, TLS handshake error) never
#: happens to produce this exact text, so it never gets misclassified as
#: permanent by accident. whatsapp_callmebot.send() returns these directly
#: (never raises); telegram.py's send() raises ValueError for the same class
#: of problem, always with a "telegram: " prefix (see _looks_like_telegram_
#: credential_error below) -- neither ever reaches a real socket first.
_PERMANENT_NO_STATUS_ERRORS = frozenset({"malformed phone", "malformed apikey"})


def _is_permanent_no_status_error(error: str | None) -> bool:
    """True only for a known credential/shape failure, never a network one.

    telegram.py's send() raises ValueError/RuntimeError for a malformed
    token, an invalid/blocked bot, or a 400 -- always prefixed "telegram: "
    (dispatch_send.py's except-Exception catch turns the raise into this
    same (status_code=None, error=str(exc)) shape a real ConnectError would
    produce, so the prefix is the only thing that still tells them apart).
    """
    if error is None:
        return False
    if error in _PERMANENT_NO_STATUS_ERRORS:
        return True
    return error.startswith("telegram: ")


def is_transient_failure(status_code: int | None, error: str | None) -> bool:
    """True for a connection-level failure, HTTP 429, or any 5xx.

    A connection-level failure (refused, reset, DNS lookup failed, TLS
    handshake failed, timeout) never carries a status code -- httpx raises
    before a response ever exists, or (webhook.py) the channel's own
    try/except turns that raise into a DeliveryResult with status_code=None.
    Those must be retried the same as a 5xx. What must NOT be retried, even
    though it also carries status_code=None, is a credential/shape problem
    the channel caught before opening a connection at all (a malformed
    token, an invalid/blocked bot, a malformed phone/apikey) --
    `_is_permanent_no_status_error` is the one place that tells the two
    apart. A 4xx other than 429 and a channel-unconfigured "skipped" outcome
    stay permanent as before (status_code is not None and < 500, or the
    caller never reaches this function for "skipped" at all).
    """
    if status_code == 429:
        return True
    if status_code is not None:
        return status_code >= 500
    return not (error is None or _is_permanent_no_status_error(error))


def compute_next_attempt_at(
    sent_at: datetime.datetime,
    attempts: int,
    now: datetime.datetime,
    retry_after_seconds: int | None,
) -> datetime.datetime:
    """When the attempt after `attempts` is due.

    The ladder (RETRY_OFFSETS_MINUTES) is anchored to `sent_at`, the first
    failure -- not to `now` -- so the schedule reads the same regardless of
    when the poller actually gets around to running it. A Retry-After header
    only ever pushes the wait later (never shorter than the ladder's own
    value), and the total wait from the first failure is capped at 30
    minutes either way.
    """
    ladder_at = sent_at + datetime.timedelta(minutes=RETRY_OFFSETS_MINUTES[attempts - 1])
    if retry_after_seconds is not None:
        requested_at = now + datetime.timedelta(seconds=max(0, retry_after_seconds))
        ladder_at = max(ladder_at, requested_at)
    return min(ladder_at, sent_at + _RETRY_CAP)


def classify_new_delivery(
    status: str,
    error: str | None,
    status_code: int | None,
    retry_after_seconds: int | None,
    sent_at: datetime.datetime,
) -> tuple[str, int, datetime.datetime | None]:
    """(status, attempts, next_attempt_at) for a row being written for the
    first time. Only a transient "failed" outcome becomes "retrying"; every
    other status (sent/skipped/queued, or a permanent failure) is stored as
    given, with attempts=1 and nothing scheduled.
    """
    if status == "failed" and is_transient_failure(status_code, error):
        return "retrying", 1, compute_next_attempt_at(sent_at, 1, sent_at, retry_after_seconds)
    return status, 1, None

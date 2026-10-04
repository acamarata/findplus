"""When does a person's place state stop being trusted? (r122 O5)

Purpose : A person state holds while the tracker that was carried goes quiet
          (spec section 5.1), but not for ever. If the carried tracker dies for
          good at School, the held "inside School" must not turn into a false
          "left School" when that tracker (or a parked one) speaks again days
          later. A state that no evidence has confirmed for STATE_EXPIRY becomes
          unknown, and the next evaluation reseeds it silently from whatever is
          reporting. No event comes from an expired state.
Inputs  : The state's `confirmed_at` (the last evaluation whose evidence agreed
          with it, migration 0014), the evaluation instant.
Outputs : A boolean.
Constraints: Pure. 12 hours is longer than a night asleep at Home or a school
          day and shorter than a tracker that died yesterday; a person state
          held 12 h past its last confirmation is the "unknown (stale)" case of
          spec section 3 (a stale tracker is never placed) applied to the state.
"""

from __future__ import annotations

from datetime import datetime, timedelta

STATE_EXPIRY = timedelta(hours=12)


def expired(confirmed_at: datetime | None, as_of: datetime) -> bool:
    """True when nothing has confirmed this state for STATE_EXPIRY.

    A state with no confirmation time at all (a row from before migration 0014
    that was never evaluated since) is not expired: it is confirmed or expired
    by the next evaluation, never guessed here.
    """
    return confirmed_at is not None and as_of - confirmed_at > STATE_EXPIRY

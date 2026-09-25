"""Parse and validate Telegram chat targets: a comma-separated list of ids/usernames.

Purpose    : One place that knows the shape of a Telegram "targets" field --
             the setup wizard, the Settings alerts card, the CLI and the API
             all read/write the same comma-separated string, and none of them
             should re-implement trimming, dedup or the id/username shapes.
Inputs     : The raw comma-separated string a person typed or pasted, or a
             list of target strings already split out.
Outputs    : A trimmed, de-duplicated (order-preserving), validated list of
             targets, or the comma string to store.
Constraints: Raises ValueError naming the exact bad entry, never a generic
             "invalid target" -- the caller (API 422 detail, CLI
             ClickException, wizard status line) shows that message as-is.
             Telegram's own id/username shapes, not a network round trip:
             this never proves a target is live, only that it's worth trying.
"""

from __future__ import annotations

import re

#: A rule of thumb, not a Telegram-documented ceiling: one bot fanning out to
#: more than this from a single rule is almost certainly a misconfiguration
#: (a pasted list of unrelated ids), and dispatch.py would otherwise send --
#: and retry -- one HTTP request per target per event with no cap at all.
MAX_TARGETS = 10

#: A Telegram numeric chat id: a bare user id (positive), a basic group
#: (negative), or a supergroup/channel (negative, starting -100...). Shape
#: only, matching store.is_valid_bot_token's own "no live check" stance.
_NUMERIC_ID_RE = re.compile(r"^-?\d{1,15}$")

#: A Telegram public username: '@' then 5-32 letters/digits/underscores
#: (Telegram's own username rule -- usernames shorter than 5 characters are
#: never issued).
_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")


def is_valid_target(value: str) -> bool:
    """True for a numeric chat/group/supergroup id or an '@username'."""
    return bool(_NUMERIC_ID_RE.fullmatch(value) or _USERNAME_RE.fullmatch(value))


def parse_targets(raw: str) -> list[str]:
    """Comma-separated targets -> trimmed, de-duplicated, validated list.

    Order is preserved (first occurrence wins on a duplicate) so the field
    reads back the way it was typed, not alphabetically re-sorted like
    channels_field.py's channel set. Raises ValueError naming the first bad
    entry, or when the result is empty or over MAX_TARGETS.
    """
    seen: list[str] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        if not is_valid_target(value):
            raise ValueError(
                f"invalid Telegram target {value!r}: use a numeric chat id "
                "(e.g. 123456789 or -1001234567890) or an @username"
            )
        if value not in seen:
            seen.append(value)
    if not seen:
        raise ValueError("at least one Telegram target is required")
    if len(seen) > MAX_TARGETS:
        raise ValueError(f"at most {MAX_TARGETS} Telegram targets are allowed, got {len(seen)}")
    return seen


def format_targets(targets: list[str]) -> str:
    """List of targets -> the comma string to store. Re-validates (§ above)."""
    return ",".join(parse_targets(",".join(targets)))

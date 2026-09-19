"""Honesty text — the exact sentences the UI, wiki and README must show verbatim.

Purpose    : One source of truth for the sentences specs/honesty.md pins, so
             `/api/config.notices`, the dashboard, and `test_honesty_text.py`
             (E10) all read the same strings instead of duplicating them.
Inputs     : None — every value here is a fixed, owner-approved sentence.
Outputs    : Six module-level constants plus the NOTICES dict `/api/config`
             serves under its `notices` key.
Constraints: Copied character-for-character from specs/honesty.md. Never
             paraphrase or shorten these; this app touches a child's location
             history and every surface must state, not overstate, what it does.
"""

from __future__ import annotations

FIND_HUB = (
    "This history consists of locations reported through Google's Find Hub network. "
    "Moto Tag uses nearby participating Android devices to report its location. "
    "Location updates can therefore be delayed, sparse, or unavailable, and this "
    "application should not be treated as real-time emergency or child-safety GPS tracking."
)

APPLE = (
    "Apple Find My locations come from nearby Apple devices and can be delayed, "
    "sparse or unavailable. Find+ can only query accessories whose keys you hold; "
    "genuine AirTags require extracting pairing keys, which most users cannot do."
)

ALERTS_LATENCY = (
    "Alerts inherit the network's delay. An arrival or departure may be reported "
    "minutes to hours late."
)

PRESENCE_STALE = (
    "A tag with no recent fix is stale, not at home and not left behind. "
    "Find+ reports it as unknown."
)

LOCK_NOT_ENCRYPTION = (
    "The app lock stops casual browsing. It does not encrypt the database; "
    "anyone with access to this user account or the disk can read it. Use FileVault."
)

NOT_AFFILIATED = (
    "Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks."
)

NOTICES: dict[str, str] = {
    "find_hub": FIND_HUB,
    "apple": APPLE,
    "alerts_latency": ALERTS_LATENCY,
    "presence_stale": PRESENCE_STALE,
    "lock_not_encryption": LOCK_NOT_ENCRYPTION,
    "not_affiliated": NOT_AFFILIATED,
}

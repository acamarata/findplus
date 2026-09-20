"""Honesty text — the exact sentences the UI, wiki and README must show verbatim.

Purpose    : One source of truth for the sentences specs/honesty.md pins, so
             `/api/config.notices`, the dashboard, and `test_honesty_text.py`
             (E10) all read the same strings instead of duplicating them.
Inputs     : None — every value here is a fixed, owner-approved sentence.
Outputs    : One module-level constant per sentence, plus the NOTICES dict
             `/api/config` serves under its `notices` key. Every generator and
             test iterates NOTICES rather than a hardcoded key list, so adding
             a sentence here is the only edit an extra notice needs.
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

WHATSAPP_RELAY = (
    "WhatsApp alerts are relayed through CallMeBot, a third-party free service. Your alert "
    "text transits CallMeBot's servers before reaching WhatsApp. Delivery is best-effort with "
    "no guarantee. Find+ is not affiliated with WhatsApp, Meta or CallMeBot."
)

WHATSAPP_SETUP = (
    "To connect WhatsApp: add +34 623 91 22 04 to your phone's contacts, then send it the "
    'message "I allow callmebot to send me messages" from your own WhatsApp. CallMeBot '
    "replies with an API key within about two minutes — paste it below."
)

ALERTS_LOCKED = "Notifications are held while Find+ is locked. Unlock to see what you missed."

NATIVE_GENERIC = (
    'By default, macOS notifications show a generic "Find+ alert" instead of who or '
    "where, because notification banners can appear on a locked screen. Turn on "
    "notification details in Settings to show the person and place — anyone who can see "
    "the screen then sees the same thing."
)

NOT_AFFILIATED = (
    "Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks."
)

CHROME_REQUIRED = (
    "Google Chrome was not found on this machine. Google sign-in drives Chrome directly "
    "and cannot run without it. Install it from https://www.google.com/chrome/ and try "
    "again."
)

NOTICES: dict[str, str] = {
    "find_hub": FIND_HUB,
    "apple": APPLE,
    "alerts_latency": ALERTS_LATENCY,
    "presence_stale": PRESENCE_STALE,
    "lock_not_encryption": LOCK_NOT_ENCRYPTION,
    "whatsapp_relay": WHATSAPP_RELAY,
    "whatsapp_setup": WHATSAPP_SETUP,
    "alerts_locked": ALERTS_LOCKED,
    "native_generic": NATIVE_GENERIC,
    "not_affiliated": NOT_AFFILIATED,
    "chrome_required": CHROME_REQUIRED,
}

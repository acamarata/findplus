"""The `people.digest` key of GET/PATCH /api/settings.

Purpose    : Expose the evening-summary preference (switch, time, people,
             channel) through the same settings body the dashboard uses.
Inputs     : The PATCH body's raw dict; a key's presence is the signal, and the
             value is a partial object that is merged over the stored one.
Outputs    : The full preference for the GET body; a write into the settings
             table through people/digest_prefs.py.
Constraints: Validation lives in people/digest_prefs.py, shared with the CLI, so
             the two cannot disagree. A bad value raises ValueError (the route
             turns it into a 422) and nothing is written.
"""

from __future__ import annotations

from typing import Any

from findplus.people import digest_prefs

WIRE_KEY = "people.digest"


def digest_field(session) -> dict[str, Any]:
    return digest_prefs.load(session)


def write_digest_fields(session, raw_body: dict[str, Any]) -> None:
    """Merge a PATCH's `people.digest` object into the stored preference."""
    if WIRE_KEY not in raw_body:
        return
    value = raw_body[WIRE_KEY]
    if not isinstance(value, dict):
        raise ValueError('people.digest must be an object, for example {"enabled": true}')
    digest_prefs.save(session, value)

"""Plain-words reasons for a suspect sighting.

Purpose    : One sentence per reason code for the API (`suspect_reason`), the
             CLI and the trips payload. The dashboard reads the same sentences
             from `web/locales/en.json` (`quality.reason.*`); a test pins the
             two copies together, as for the alert channel names.
Inputs     : Reason codes from `quality.rules`.
Outputs    : A sentence, or None when there is nothing to say.
Constraints: No numbers in the sentences (the codes carry no distances). The
             tail clause says what suspect means, so it is never a surprise.
"""

from __future__ import annotations

from collections.abc import Iterable

from findplus.quality import rules as r

LEFT_OUT = "Left out of stays, trips and alerts."

_WRONG = "This sighting looks wrong: "

REASON_TEXT: dict[str, str] = {
    r.ABA_TELEPORT: f"{_WRONG}it jumps far away and back within minutes. {LEFT_OUT}",
    r.IMPOSSIBLE_SPEED: f"{_WRONG}it implies a speed no tracker travels. {LEFT_OUT}",
    r.EDGE_STRAY: f"{_WRONG}it is far from the sightings around it. {LEFT_OUT}",
    r.JUMP_UNCONFIRMED: (
        "This sighting jumped far and nothing has confirmed it yet. "
        "It is held back until the next sighting arrives."
    ),
    r.SIBLING_DISAGREE: (
        f"{_WRONG}the person's other trackers agree on a place far from here, "
        f"and this tracker has not backed it up. {LEFT_OUT}"
    ),
    r.LOW_ACCURACY: "The network could only place this sighting within a wide area.",
    r.CLOCK_SKEW: "The time on this sighting is later than when it was received.",
}

#: Reasons that make a fix suspect on their own; the soft ones never do.
_HARD = (
    r.ABA_TELEPORT,
    r.IMPOSSIBLE_SPEED,
    r.EDGE_STRAY,
    r.JUMP_UNCONFIRMED,
    r.SIBLING_DISAGREE,
)


def reason_text(codes: Iterable[str]) -> str | None:
    """The sentence for the most serious code in `codes`, or None when empty."""
    wanted = set(codes)
    for code in (*_HARD, r.LOW_ACCURACY, r.CLOCK_SKEW):
        if code in wanted:
            return REASON_TEXT[code]
    return None

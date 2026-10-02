"""Read a tracker's name: whose it is and what it is (specs/people-and-presence.md § 2).

Purpose : "Zaid Shoes Red" -> owner "Zaid", role shoes, confidence high. The
          suggestion builder (people/suggestions.py) clusters trackers by the
          owner token this returns; nothing is ever grouped without a click.
Inputs  : One display name (label, else provider name), never the id tail.
Outputs : NameReading per tracker.
Constraints: Pure. Exact owner tokens only: no fuzzy matching, so "Ali" and
          "Alia" stay apart. Normalisation (NFKC, casefold, no diacritics)
          is for matching only; the owner keeps its original casing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from findplus.people.roles import BRAND_ROLE_WORDS, ROLE_WORDS

_SPLIT_RE = re.compile(r"[\s_\-.()/,]+")
#: "Zaid's" -> "Zaid", "James'" -> "James".
_APOSTROPHES = "'\u2019"
_POSSESSIVE_RE = re.compile(f"(?:[{_APOSTROPHES}]s|[{_APOSTROPHES}])$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d+$")
#: Model codes and ordinals: 8a, s23, 2nd, 11th, x1.
_MODEL_RE = re.compile(r"^(\d+[a-z]{1,2}|[a-z]\d+[a-z]?|\d+(st|nd|rd|th))$")


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


COLOURS = _words(
    "red white black blue green yellow pink purple orange grey gray brown rose gold "
    "silver navy teal beige cream maroon violet"
)
_MODIFIERS = _words(
    "pro max plus ultra mini lite new old spare first second third tag tracker airtag "
    "smarttag tile chipolo my the of"
)
#: Brands that are not role words. A brand-only name ("Moto Tag 2") names no
#: owner with any confidence.
BRANDS = _words(
    "moto motorola samsung google apple nike adidas puma huawei xiaomi oneplus sony "
    "garmin lenovo dell hp asus"
)
#: Names commonly given to pets, plus words that say "animal". Only a guess:
#: the preview still asks "person or pet?" for every one-token name.
PET_WORDS = _words(
    "dog cat puppy kitten kitty pet meong miaw meow shadow luna bella max charlie milo "
    "simba oreo coco mochi nala leo loki oliver tiger smokey ginger pepper buddy rocky "
    "daisy molly bailey toby zeus whiskers snowy felix garfield bruno"
)


@dataclass(frozen=True)
class NameReading:
    """What one tracker name says about its owner and role."""

    device_id: str
    name: str
    #: Normalised owner token used to cluster, or None ("Whose is this?").
    owner_key: str | None
    #: The owner token as written in the name, for display.
    owner_display: str | None
    #: Role from the last role word in the name, or None.
    role: str | None
    #: high (owner + role word) | medium (owner only) | low (owner is a colour
    #: or brand) | None (no owner).
    confidence: str | None
    #: owner_is_colour | owner_is_brand
    flags: tuple[str, ...] = ()
    #: True when the name is a single token with no role word.
    lone_token: bool = False

    @property
    def looks_like_pet(self) -> bool:
        return self.role == "collar" or (self.owner_key or "") in PET_WORDS


def match_key(text: str) -> str:
    """NFKC, casefold, diacritics stripped: the form two tokens are compared in."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokens(name: str) -> list[tuple[str, str]]:
    """(display, key) per token, possessives reduced to the bare word."""
    out: list[tuple[str, str]] = []
    for raw in _SPLIT_RE.split(unicodedata.normalize("NFKC", name)):
        bare = _POSSESSIVE_RE.sub("", raw) if len(raw) > 2 else raw
        if bare:
            out.append((bare, match_key(bare)))
    return out


def _is_modifier(key: str) -> bool:
    return (
        key in COLOURS
        or key in _MODIFIERS
        or bool(_DIGITS_RE.match(key))
        or bool(_MODEL_RE.match(key))
    )


def _owner(toks: list[tuple[str, str]]) -> tuple[str | None, str | None, tuple[str, ...]]:
    """(owner_key, owner_display, flags) from the classified tokens (spec § 2 step 3)."""
    for display, key in toks:
        if key in ROLE_WORDS or key in BRANDS or _is_modifier(key) or len(key) < 2:
            continue
        return key, display, ()
    if toks:
        display, key = toks[0]
        if key in COLOURS:
            return key, display, ("owner_is_colour",)
        if key in BRANDS and key not in BRAND_ROLE_WORDS:
            return key, display, ("owner_is_brand",)
    return None, None, ()


def read_name(device_id: str, name: str) -> NameReading:
    """Classify one tracker name into owner, role and confidence."""
    toks = tokens(name or "")
    roles = [ROLE_WORDS[key] for _, key in toks if key in ROLE_WORDS]
    role = roles[-1] if roles else None
    owner_key, owner_display, flags = _owner(toks)
    if owner_key is None:
        confidence = None
    elif flags:
        confidence = "low"
    else:
        confidence = "high" if role else "medium"
    return NameReading(
        device_id=device_id,
        name=name,
        owner_key=owner_key,
        owner_display=owner_display,
        role=role,
        confidence=confidence,
        flags=flags,
        lone_token=len(toks) == 1 and role is None,
    )


def cluster(readings: list[NameReading]) -> tuple[dict[str, list[NameReading]], list[NameReading]]:
    """Group readings by exact owner key; the rest have no owner token."""
    groups: dict[str, list[NameReading]] = {}
    unowned: list[NameReading] = []
    for reading in readings:
        if reading.owner_key is None:
            unowned.append(reading)
        else:
            groups.setdefault(reading.owner_key, []).append(reading)
    return groups, unowned


_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def cluster_confidence(members: list[NameReading]) -> str:
    """The weakest member's confidence: one "Rose Bag" makes the whole group low."""
    return min((m.confidence or "low" for m in members), key=_CONFIDENCE_ORDER.__getitem__)

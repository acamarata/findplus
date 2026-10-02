"""Place kinds: home, school, work, family, shop, other (spec § 1.3).

Purpose : Home is special (left-behind alerts are off there, the day summary
          opens "Overnight at Home"), so a place carries a kind. The dialog and
          the API guess it from the name ("Grandma's" -> family) for the owner
          to confirm; nothing else depends on the guess.
Inputs  : A place name, or a kind to validate.
Outputs : A kind from db.models_people.PLACE_KINDS.
Constraints: Pure. The column has no CHECK (no rebuild of `places`), so this
          validation is the only guard.
"""

from __future__ import annotations

import re

from findplus.db.models_people import PLACE_KINDS

_WORDS = {
    # Family first: "Grandma's House" is Grandma's, not a home.
    "family": (
        "grandma", "grandpa", "granny", "grandad", "granddad", "nana", "nan", "papa",
        "aunt", "auntie", "uncle", "cousin", "nanny", "jaddah", "jaddi",
    ),
    "home": ("home", "house", "flat", "apartment"),
    "school": (
        "school", "academy", "college", "university", "uni", "kindergarten", "nursery",
        "preschool", "madrasa", "madrassa", "daycare",
    ),
    "work": ("work", "office", "job", "workplace"),
    "shop": ("shop", "store", "market", "supermarket", "mall", "grocery"),
}  # fmt: skip


def guess_place_kind(name: str) -> str:
    """The kind a place name suggests, else 'other'."""
    words = re.split(r"[^a-z]+", re.sub("['\u2019]s\\b", "", name.casefold()))
    for kind, vocab in _WORDS.items():
        if any(w in vocab for w in words):
            return kind
    return "other"


def validate_place_kind(kind: str | None) -> str | None:
    if kind is not None and kind not in PLACE_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(PLACE_KINDS)}")
    return kind

"""Tracker roles and carry weights (specs/people-and-presence.md § 1.2).

Purpose : How much a tracker's position says about where its person is. A
          phone is pocketed (1.0); a bag is taken off and left often (0.5); a
          bike is parked for hours (0.4). The inference engine multiplies
          these by age, motion and accuracy factors (people/infer.py).
Inputs  : A role id (db.models_people.DEVICE_ROLES) and an optional per-tracker
          override from devices.carry_weight.
Outputs : Weights in [0, 1]; the role vocabulary naming.py reads names with.
Constraints: Pure. The weights are judgement calls, not measurements (spec
          § 13 "Weights are made up"); the per-tracker override and the dry
          run are the answer, so every value lives in this one table.
"""

from __future__ import annotations

from findplus.db.models_people import DEVICE_ROLES

#: Default carry weight per role. 0 means "never used to place the person".
ROLE_WEIGHTS: dict[str, float] = {
    "phone": 1.0,
    "watch": 1.0,
    "collar": 1.0,
    "wallet": 0.8,
    "keys": 0.8,
    "shoes": 0.8,
    "bag": 0.5,
    "jacket": 0.5,
    "bike": 0.4,
    "scooter": 0.4,
    "tablet": 0.4,
    "laptop": 0.4,
    "car": 0.2,
    "luggage": 0.2,
    "other": 0.5,
}

#: Words in a tracker name that say what it is attached to (spec § 2 step 2).
#: Matched after normalisation (casefold, no diacritics, possessive dropped).
ROLE_WORDS: dict[str, str] = {
    **dict.fromkeys(("pixel", "iphone", "galaxy", "phone", "mobile"), "phone"),
    **dict.fromkeys(("watch", "fitbit"), "watch"),
    **dict.fromkeys(("shoe", "shoes", "sneaker", "sneakers", "trainers", "boots"), "shoes"),
    **dict.fromkeys(("bag", "backpack", "schoolbag", "satchel", "purse"), "bag"),
    **dict.fromkeys(("key", "keys", "keyring"), "keys"),
    "wallet": "wallet",
    **dict.fromkeys(("bike", "bicycle"), "bike"),
    "scooter": "scooter",
    **dict.fromkeys(("car", "van"), "car"),
    **dict.fromkeys(("jacket", "coat"), "jacket"),
    **dict.fromkeys(("ipad", "tablet", "tab"), "tablet"),
    **dict.fromkeys(("laptop", "macbook"), "laptop"),
    **dict.fromkeys(("suitcase", "luggage"), "luggage"),
    "collar": "collar",
}

#: Role words that are also brand names. A brand never names an owner.
BRAND_ROLE_WORDS = frozenset({"pixel", "iphone", "galaxy", "fitbit", "ipad", "macbook"})

if set(ROLE_WEIGHTS) != set(DEVICE_ROLES):  # pragma: no cover - import-time guard
    raise RuntimeError("ROLE_WEIGHTS must cover exactly db.models_people.DEVICE_ROLES")


def validate_role(role: str | None) -> str | None:
    """The role as stored, or ValueError naming the allowed values."""
    if role is None:
        return None
    role = role.strip().lower()
    if role not in ROLE_WEIGHTS:
        raise ValueError(f"role must be one of: {', '.join(DEVICE_ROLES)}")
    return role


def validate_weight(weight: float | None) -> float | None:
    """A carry-weight override in [0, 1], or None to use the role default."""
    if weight is None:
        return None
    if not 0.0 <= float(weight) <= 1.0:
        raise ValueError("carry_weight must be between 0 and 1")
    return float(weight)


def effective_weight(role: str | None, override: float | None) -> float:
    """The weight inference uses: the override, else the role default, else 'other'."""
    if override is not None:
        return float(override)
    return ROLE_WEIGHTS.get(role or "other", ROLE_WEIGHTS["other"])

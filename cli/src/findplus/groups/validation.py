"""Group field validation: cluster radius, stale window, and quorum grammar.

Purpose : Guard the values groups.repo.create_group/update_group accept before they
          reach the DB, split out of repo.py to keep it under the 300-line cap. Mirrors
          findplus.places.repo._validate_place_fields's role and error-message style.
Inputs  : Plain keyword arguments (None means "field not being set").
Outputs : None; raises ValueError with an exact message the callers (API routes, CLI)
          map to HTTP 422 / a non-zero CLI exit without guessing.
Constraints: Pure (no DB access), except that the icon grammar is checked by
          findplus.labels.validate_icon, which reads the pinned icon table once.
          Ranges come from specs/data-model.md § Migration 0005 `groups` CHECK
          constraints; quorum grammar from specs/engines.md § quorum; icon
          grammar from specs/labels-and-icons.md § Icon grammar.
Reuse: called from findplus.groups.repo only.
"""

from __future__ import annotations

from findplus.labels import validate_icon


def _valid_quorum(quorum: str) -> bool:
    """`any` | `majority` | `all` | a decimal integer string 1-20 (specs/engines.md § quorum)."""
    if quorum in ("any", "majority", "all"):
        return True
    return quorum.isdigit() and 1 <= int(quorum) <= 20


def validate_group_fields(
    *,
    quorum: str | None = None,
    cluster_radius_meters: int | None = None,
    stale_after_minutes: int | None = None,
    icon: str | None = None,
) -> None:
    if cluster_radius_meters is not None and not (25 <= cluster_radius_meters <= 2000):
        raise ValueError("cluster_radius_meters must be 25-2000")
    if stale_after_minutes is not None and not (10 <= stale_after_minutes <= 1440):
        raise ValueError("stale_after_minutes must be 10-1440")
    if quorum is not None and not _valid_quorum(quorum):
        raise ValueError("quorum must be any, majority, all, or an integer 1-20")
    if icon is not None:
        validate_icon(icon)

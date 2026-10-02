"""The one value object the scoring rules and trip segmentation share.

Purpose    : A sighting reduced to what geometry needs. Lives in `quality` (not
             `trips`) so `quality.rules` can import it without pulling in trip
             segmentation, which itself imports the rules.
Inputs     : Built by `trips.service` and `quality.store` from stored rows.
Outputs    : `Fix`, re-exported by `findplus.trips.models` for existing callers.
Constraints: Pure data; no DB or HTTP. Timestamps are tz-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Accuracy assumed when a fix reports none. Crowd-sourced fixes are rarely better.
DEFAULT_ACCURACY_M = 50.0


@dataclass(frozen=True, slots=True)
class Fix:
    """One sighting. `accuracy_m` is the radius the network reported, if any."""

    id: int
    t: datetime
    lat: float
    lon: float
    accuracy_m: float | None = None
    #: When this computer first got the fix, and whether the owner's own device
    #: reported it. Only the quality rules read these; segmentation ignores them.
    fetched_at: datetime | None = None
    own_report: bool = False

    @property
    def acc(self) -> float:
        return self.accuracy_m if self.accuracy_m else DEFAULT_ACCURACY_M

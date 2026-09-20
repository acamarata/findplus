"""Device and group labels: palette, icon grammar, validation.

Purpose : One place that owns what a label, an icon id and a colour may be, so
          the API, the CLI, the exporters and the widget payload all agree.
Inputs  : User-supplied label/icon/colour strings; the pinned Lucide id table at
          packaging/data/lucide-subset.json (findplus/_data/ inside a wheel).
Outputs : Validated strings, or `ValueError` carrying the exact message the API
          returns as a 422 detail.
Constraints:
    - `DEVICE_PALETTE` and `palette_color_for` are duplicated verbatim in
      migration 0007. An Alembic revision must stay runnable forever, so it
      cannot import this module; cli/tests/test_labels.py asserts the two copies
      never drift. A device gets the same colour whether it predates 0007 or was
      discovered after it.
    - Bare `letter` is dynamic: the character is computed at render time from the
      current label or name, so renaming a device moves its badge with no write.
Reuse   : imported by api/routes_devices, api/routes_core, api/routes_groups,
          groups/repo, cli/cmd_devices, exporters and the widget payload.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from pathlib import Path

#: First eight = the retired web/app/state.js TRACK_COLORS in their exact order.
DEVICE_PALETTE = [
    "#4f8cf7",
    "#e7663f",
    "#37c67a",
    "#c77ae6",
    "#e7b53f",
    "#3fc9d6",
    "#e64f7a",
    "#8fb43f",
    "#f2994a",
    "#9b6bd6",
    "#4fd6a8",
    "#d65f5f",
]

_ICON_RE = re.compile(r"^(lucide:[a-z0-9-]+|letter:[A-Z0-9]|letter|none)$")
_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")


def palette_color_for(device_id: str) -> str:
    """The stable palette colour for a device id (same formula as migration 0007)."""
    digest = hashlib.sha1(device_id.encode("utf-8")).hexdigest()
    return DEVICE_PALETTE[int(digest, 16) % 12]


def _data_path() -> Path:
    packaged = Path(__file__).parent / "_data" / "lucide-subset.json"
    if packaged.exists():
        return packaged
    from findplus.config import PROJECT_ROOT

    return PROJECT_ROOT.parent / "packaging" / "data" / "lucide-subset.json"


@functools.lru_cache(maxsize=1)
def lucide_subset() -> list[dict[str, str]]:
    """The pinned 48-id icon table, `[{"id": "lucide:dog", "group": "pets"}, ...]`."""
    return json.loads(_data_path().read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _lucide_ids() -> frozenset[str]:
    return frozenset(row["id"].split(":", 1)[1] for row in lucide_subset())


def validate_label(label: str | None) -> str | None:
    """Trim; `None` and a blank string both mean "no label"."""
    if label is None:
        return None
    trimmed = label.strip()
    if len(trimmed) > 40:
        raise ValueError("label must be 40 characters or fewer")
    return trimmed or None


def validate_icon(icon: str) -> str:
    """One of `lucide:<name>` (pinned set), `letter:<X>`, `letter`, `none`."""
    if not _ICON_RE.match(icon):
        raise ValueError("icon must match lucide:<name>, letter:<char>, letter, or none")
    if icon.startswith("lucide:") and icon.split(":", 1)[1] not in _lucide_ids():
        raise ValueError("icon must be one of the available lucide icon ids")
    return icon


def validate_color(color: str) -> str:
    """Lowercase `#rrggbb` only, so stored values compare as plain strings."""
    if not _COLOR_RE.match(color):
        raise ValueError("color must be a lowercase #rrggbb hex value")
    return color


def resolve_icon_letter(icon: str, label: str | None, name: str) -> str | None:
    """The character a badge shows, or `None` for `lucide:*`, `none` and no text.

    Bare `letter` reads the live label, falling back to the provider name, so a
    renamed device's badge follows the new name. With neither to read from there
    is no honest character to invent, so the caller draws the plain dot.
    """
    if icon.startswith("letter:"):
        return icon.split(":", 1)[1]
    if icon != "letter":
        return None
    text = (label or "").strip() or (name or "").strip()
    return text[0].upper() if text else None

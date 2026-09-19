"""Content-Disposition construction for the export endpoints.

Purpose    : Build a download header that a device or group name cannot break
             out of, while still handing the browser the real, accented name.
Inputs     : A filename assembled from user-chosen device/group names.
Outputs    : One `attachment; filename="..."; filename*=UTF-8''...` string.
Constraints:
    - The quoted `filename=` form is ASCII-only and restricted to
      `[A-Za-z0-9._-]`, so a name holding `"`, `;`, CR or LF can neither close
      the quoted string nor add a header directive.
    - The RFC 5987 `filename*` form carries the real name, percent-encoded;
      every current browser prefers it, so nothing is lost by slugifying the
      fallback hard.
"""

from __future__ import annotations

import re
from urllib.parse import quote

__all__ = ["content_disposition", "slugify_filename"]

#: Everything a user-chosen name may contribute to the ASCII filename.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_filename(name: str) -> str:
    """Reduce a name to `[A-Za-z0-9._-]`, never empty, never longer than 100."""
    slug = _UNSAFE.sub("-", name).strip("-.") or "export"
    return slug[:100]


def content_disposition(filename: str) -> str:
    """The full attachment header for `filename`, slugified plus RFC 5987."""
    return (
        f'attachment; filename="{slugify_filename(filename)}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )

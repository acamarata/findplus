"""Shared fixture and builders for the /api/apple/accessories route tests,
split out of test_routes_apple_accessories.py (E13 stage 2, size cap).

Purpose    : URL, the key-material builder and the leftover-file check both
             test_routes_apple_accessories.py and
             test_routes_apple_accessories_limits.py need. Each file keeps
             its own small `client` fixture (importing a fixture used as a
             same-named test parameter trips ruff's F811).
Inputs     : n/a.
Outputs    : n/a.
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

import base64

from findplus.config import get_settings

URL = "/api/apple/accessories"


def _key_b64(filler: bytes = b"x") -> str:
    """28 raw bytes: a P-224 scalar, the only key size Find My uses."""
    return base64.b64encode(filler * 28).decode()


def _leftovers() -> list:
    return list(get_settings().state_dir.glob(".accessory-upload-*"))

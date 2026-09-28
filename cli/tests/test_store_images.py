"""The committed Chrome Web Store icon and promo tile stay in sync with the script."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "packaging" / "scripts" / "gen-store-images.py"
_IMAGES = _ROOT / ".github" / "docs" / "chrome-web-store" / "images"


def _dimensions(png: Path) -> tuple[int, int]:
    data = png.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def test_store_images_are_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_icon_and_promo_have_the_store_dimensions() -> None:
    assert _dimensions(_IMAGES / "icon-128.png") == (128, 128)
    assert _dimensions(_IMAGES / "promo-440x280.png") == (440, 280)

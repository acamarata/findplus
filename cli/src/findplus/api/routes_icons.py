"""Custom device/group icons: upload, list, serve, delete.

Purpose    : PNG icons a user uploads instead of picking a pinned Lucide id
             or a letter badge (specs/labels-and-icons.md custom icon
             amendment). Content-addressed: the id is a 16-hex-char prefix
             of the file's own SHA-256, so the same PNG uploaded twice is
             one file and the same id, and nothing here ever has to invent
             or track a name.
Inputs     : `POST /api/icons/custom` (multipart, field "file"); a
             `custom:<id>` from `GET /api/icons/custom` or `DELETE .../<id>`.
Outputs    : `{"id": "custom:<16 hex>"}` on upload; a bare list of ids on
             list; the raw PNG bytes on the `.png` route; 204 on delete.
Constraints: PNG only, streamed-bounded to 64 KiB (`_bounded_upload.py`'s
             helper, shared with the accessory-key upload), square-ish
             16-512 px. No Pillow: it is a dev/test-only dependency here
             (pyproject.toml `[project.optional-dependencies].dev`), so the
             verified bytes are stored exactly as uploaded, not
             re-encoded. Every route sits under `/api/`, not in
             routes_core.py's `_PUBLIC`, so the app lock and origin guard
             already gate it the same as every other data route.
"""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from findplus.api._bounded_upload import read_bounded_form
from findplus.config import get_settings
from findplus.db.models import Device, Group
from findplus.db.session import session_scope

#: A picker swatch, not a photo: generous enough for any reasonable app icon,
#: small enough that a run of uploads never dents the disk.
_MAX_ICON_BYTES = 64 * 1024
_MULTIPART_OVERHEAD_BYTES = 4 * 1024

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MIN_DIM = 16
_MAX_DIM = 512
_MAX_ASPECT_SKEW = 0.10

_ID_RE_LEN = 16
#: Exactly the shape `_content_id()` produces — never trusted from a client
#: without this check first, so a path segment can never reach the
#: filesystem as anything but a 16-hex-char component (review finding N2).
_ICON_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _icons_dir() -> Path:
    """`~/.findplus/icons/`, created 0700 on first use (harden_permissions
    only sweeps the paths it already knows about; this one is younger)."""
    import os

    d = get_settings().icons_dir
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _reject_oversized_content_length(request: Request) -> None:
    """413 from Content-Length alone, before the body is parsed. A cheap
    short-circuit only — `read_bounded_form()` is the real guard, same
    two-layer shape as routes_auth.py's accessory upload."""
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return
    try:
        declared = int(raw_length)
    except ValueError:
        return
    if declared > _MAX_ICON_BYTES + _MULTIPART_OVERHEAD_BYTES:
        raise HTTPException(status_code=413, detail="icon too large")


def _parse_ihdr(data: bytes) -> tuple[int, int]:
    """(width, height) from a PNG's first chunk, or 415 if it is not one.

    A real PNG's IHDR is always the very first chunk, length 13, right after
    the 8-byte signature — that is what tells a genuine PNG apart from an
    SVG, a JPEG, a GIF, or a polyglot with a PNG signature glued onto some
    other payload.
    """
    if len(data) < 8 + 8 + 13 or not data.startswith(_PNG_SIGNATURE):
        raise HTTPException(status_code=415, detail="file must be a PNG image")
    chunk_len = int.from_bytes(data[8:12], "big")
    chunk_type = data[12:16]
    if chunk_len != 13 or chunk_type != b"IHDR":
        raise HTTPException(status_code=415, detail="file must be a PNG image")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _validate_dimensions(width: int, height: int) -> None:
    if not (_MIN_DIM <= width <= _MAX_DIM and _MIN_DIM <= height <= _MAX_DIM):
        raise HTTPException(
            status_code=422, detail=f"icon must be {_MIN_DIM}-{_MAX_DIM}px square-ish"
        )
    skew = abs(width - height) / max(width, height)
    if skew > _MAX_ASPECT_SKEW:
        raise HTTPException(
            status_code=422, detail="icon must be square-ish (aspect ratio 1:1 ±10%)"
        )


def _content_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:_ID_RE_LEN]


def _validate_icon_id(icon_id: str) -> None:
    """404 for anything that is not exactly 16 lowercase hex chars.

    By design, not by accident (review finding N2): every id this route ever
    issues comes from `_content_id()` and looks exactly like this, so a path
    segment that does not is refused before it is ever joined onto
    `_icons_dir()` — never mind whether Starlette's own `{icon_id}` converter
    (which already excludes "/") would have been enough on its own.
    """
    if not _ICON_ID_RE.fullmatch(icon_id):
        raise HTTPException(status_code=404, detail="unknown custom icon")


def _reject_apng_and_trailing_bytes(data: bytes) -> None:
    """415 for an animated PNG (an `acTL` chunk) or bytes glued on after IEND.

    A bare IHDR check (`_parse_ihdr`) lets both through: an APNG is still a
    structurally valid PNG, and nothing about the first chunk says whether
    more data follows the last one. Walked explicitly here (review finding
    N3) rather than left as an accident of what happens to get read.
    """
    pos = 8
    n = len(data)
    while pos + 8 <= n:
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunk_type = data[pos + 4 : pos + 8]
        if chunk_type == b"acTL":
            raise HTTPException(status_code=415, detail="animated PNG is not supported")
        pos += 8 + length + 4
        if chunk_type == b"IEND":
            if pos != n:
                raise HTTPException(status_code=415, detail="file has trailing data after IEND")
            return
    raise HTTPException(status_code=415, detail="file must be a PNG image")


async def _read_icon_bytes(request: Request) -> bytes:
    """The uploaded PNG's bytes, bounded while streaming regardless of what
    Content-Length claims (G1, same shape as the accessory-key upload)."""
    _reject_oversized_content_length(request)
    form = await read_bounded_form(request, _MAX_ICON_BYTES + _MULTIPART_OVERHEAD_BYTES)
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise HTTPException(status_code=422, detail="multipart body requires a 'file' part")
    data = await upload.read(_MAX_ICON_BYTES + 1)
    if len(data) > _MAX_ICON_BYTES:
        raise HTTPException(status_code=413, detail="icon too large")
    return data


async def upload_custom_icon(request: Request) -> dict[str, str]:
    data = await _read_icon_bytes(request)
    width, height = _parse_ihdr(data)
    _reject_apng_and_trailing_bytes(data)
    _validate_dimensions(width, height)
    icon_id = _content_id(data)
    path = _icons_dir() / f"{icon_id}.png"
    if not path.exists():
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        path.write_bytes(data)
    return {"id": f"custom:{icon_id}"}


def list_custom_icons() -> list[str]:
    """Every uploaded icon's id, sorted, so a picker's list is stable."""
    return sorted(f"custom:{p.stem}" for p in _icons_dir().glob("*.png"))


def get_custom_icon(icon_id: str) -> Response:
    _validate_icon_id(icon_id)
    path = _icons_dir() / f"{icon_id}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="unknown custom icon")
    return Response(
        content=path.read_bytes(),
        media_type="image/png",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400",
        },
    )


def _icon_in_use(icon: str) -> bool:
    with session_scope() as session:
        used_by_device = session.scalar(select(Device.device_id).where(Device.icon == icon))
        if used_by_device is not None:
            return True
        used_by_group = session.scalar(select(Group.id).where(Group.icon == icon))
        return used_by_group is not None


def delete_custom_icon(icon_id: str) -> Response:
    _validate_icon_id(icon_id)
    icon = f"custom:{icon_id}"
    path = _icons_dir() / f"{icon_id}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="unknown custom icon")
    if _icon_in_use(icon):
        raise HTTPException(status_code=409, detail="icon is in use by a device or group")
    path.unlink()
    return Response(status_code=204)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["icons"])
    router.add_api_route("/icons/custom", upload_custom_icon, methods=["POST"], status_code=201)
    router.add_api_route("/icons/custom", list_custom_icons, methods=["GET"])
    router.add_api_route("/icons/custom/{icon_id}.png", get_custom_icon, methods=["GET"])
    router.add_api_route("/icons/custom/{icon_id}", delete_custom_icon, methods=["DELETE"])
    return router

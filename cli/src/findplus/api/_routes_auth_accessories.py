"""Body parsing for POST /api/apple/accessories.

Purpose    : Split out of routes_auth.py (S11/WP8 follow-on: the new sign-out
             and cancel routes pushed that file over the per-file line cap,
             PRI rule 7) so the accessory-upload parsing keeps its own
             comments without crowding the auth routes it has nothing to do
             with. Accepts either a multipart upload (a .plist file) or a
             JSON body (name + private_key_b64) for one accessory
             registration.
Inputs     : the raw Request, and a Settings (state_dir, to stage an
             uploaded plist).
Outputs    : read_accessory_body() -> (name, plist_path, private_key_b64,
             allow_overwrite). The caller (routes_auth.apple_accessories)
             owns removing plist_path once add_accessory() has read it.
Constraints: Never buffers past MAX_PLIST_BYTES + MULTIPART_OVERHEAD_BYTES
             (CR-C-m4). A staged plist is written 0600 before any key
             material lands in it (PRI hard rule 9), the same order
             save_account()/add_accessory() use.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException, Request

from findplus.api._bounded_upload import (
    read_bounded_form,
    read_bounded_json,
    reject_oversized_content_length,
)

#: A plist export of a tag's key is a few hundred bytes. 64 KiB is generous and
#: still bounds what an oversized body can cost before anything is parsed.
MAX_PLIST_BYTES = 64 * 1024

#: Multipart framing (boundary markers, the two part headers, the 'name'
#: field) adds a small, bounded amount on top of the plist bytes themselves.
MULTIPART_OVERHEAD_BYTES = 4 * 1024


def _parse_allow_overwrite(raw: object) -> bool:
    """The JSON bool, or the multipart form's string ("true"/"false").

    Anything else (missing, "false", a stray non-bool) keeps the strict
    web default: no overwrite unless the caller says so (CF-P2-19).
    """
    if isinstance(raw, bool):
        return raw
    return isinstance(raw, str) and raw.strip().lower() == "true"


async def _read_multipart_accessory_body(
    request: Request, settings
) -> tuple[str, Path | None, str | None, bool]:
    """The multipart/form-data half of read_accessory_body."""
    form = await read_bounded_form(request, MAX_PLIST_BYTES + MULTIPART_OVERHEAD_BYTES)
    raw_name = form.get("name")
    upload = form.get("plist")
    if not isinstance(raw_name, str) or upload is None or isinstance(upload, str):
        raise HTTPException(
            status_code=422, detail="multipart body requires 'name' and a 'plist' file"
        )
    if upload.size is not None and upload.size > MAX_PLIST_BYTES:
        raise HTTPException(status_code=413, detail="plist too large")

    plist_bytes = await upload.read(MAX_PLIST_BYTES + 1)
    # Checked on the bytes already read, before any write.
    if len(plist_bytes) > MAX_PLIST_BYTES:
        raise HTTPException(status_code=413, detail="plist too large")
    plist_path = settings.state_dir / f".accessory-upload-{uuid.uuid4().hex}.plist"
    # 0600 BEFORE the key material is written, the same order save_account()
    # and add_accessory() use. state_dir is 0700, but a private key must not
    # rest in a default-mode file even for the length of one request.
    plist_path.touch(mode=0o600, exist_ok=False)
    plist_path.chmod(0o600)
    plist_path.write_bytes(plist_bytes)
    return raw_name, plist_path, None, _parse_allow_overwrite(form.get("allow_overwrite"))


async def read_accessory_body(
    request: Request, settings
) -> tuple[str, Path | None, str | None, bool]:
    """(name, plist_path, private_key_b64, allow_overwrite) from whichever body shape arrived.

    FastAPI parses one body as form data or JSON, so Content-Type picks the
    branch. `allow_overwrite` defaults to False in both; the dashboard's
    "Replace existing" confirm is the only caller sending true (CF-P2-19).
    Both share the same size cap (CR-C-m4): the JSON branch used to buffer
    an unbounded body before its 422.
    """
    reject_oversized_content_length(request, MAX_PLIST_BYTES + MULTIPART_OVERHEAD_BYTES)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        return await _read_multipart_accessory_body(request, settings)

    try:
        payload = await read_bounded_json(request, MAX_PLIST_BYTES + MULTIPART_OVERHEAD_BYTES)
    except HTTPException:
        raise
    except Exception as exc:
        # An unparseable body is a client error, not a 500. Starlette raises
        # json.JSONDecodeError here, which no handler above would have caught.
        raise HTTPException(status_code=422, detail="body must be JSON or multipart") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="JSON body must be an object")
    name = payload.get("name")
    if not isinstance(name, str):
        raise HTTPException(status_code=422, detail="'name' is required")
    overwrite = _parse_allow_overwrite(payload.get("allow_overwrite"))
    return name, None, payload.get("private_key_b64"), overwrite

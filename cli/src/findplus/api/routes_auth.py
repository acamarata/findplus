"""In-dashboard sign-in routes for Google Find Hub and Apple Find My.

Purpose    : HTTP over the job runners in providers/google_findhub/browser.py
             (and, from P2-E6-W3-S1-T3, providers/apple_findmy/web_auth.py)
             plus the provider-status aggregate, so signing in never needs a
             terminal (specs/auth-ui.md §3, D-P2-6).
Inputs     : JSON request bodies; a `job_id` query parameter.
Outputs    : 200/202 on success; 400/403/404/409/422 typed errors.
Constraints: Only HTTP mapping lives here — no Chrome, no findmy, no state.
             None of these paths join `_PUBLIC`, so the app lock gates them all
             (401 while locked, decided before any handler body runs). The
             router's prefix is "/api", not "/api/auth", because
             specs/auth-ui.md §3 pins `POST /api/apple/accessories` outside the
             /api/auth subtree and one mount point is better than two. Every
             handler closes over nothing, so they are module-level and
             build_router only registers them (E13 loop-1 function-cap
             refactor; routes and signatures unchanged).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from findplus.api._bounded_upload import read_bounded_form
from findplus.config import get_settings
from findplus.providers.apple_findmy.accessories import add_accessory
from findplus.providers.apple_findmy.web_auth import (
    AppleAuthAlreadyRunningError,
    InvalidAppleCodeError,
    UnknownAppleJobError,
    get_apple_auth_progress,
    start_apple_auth,
    submit_apple_code,
)
from findplus.providers.auth_status import build_auth_status
from findplus.providers.google_findhub.browser import (
    ChromeNotFoundError,
    GoogleAuthAlreadyRunningError,
    get_google_auth_progress,
    start_google_auth,
)


class AppleStartBody(BaseModel):
    apple_id: str
    password: str


class AppleCodeBody(BaseModel):
    job_id: str
    code: str


def _require_origin_signal(request: Request) -> None:
    """403 when neither Origin nor Sec-Fetch-Site is present (specs/auth-ui.md §8).

    OriginGuardMiddleware only refuses a header that is PRESENT and disallowed,
    so a request carrying neither passes it — which is right for the CLI and
    the MCP client, and wrong for the routes that start a sign-in. No browser
    or Tauri caller omits both. This supplements that middleware on those
    routes only; it never replaces it.
    """
    if not request.headers.get("origin") and not request.headers.get("sec-fetch-site"):
        raise HTTPException(status_code=403, detail="missing Origin/Sec-Fetch-Site")


def _require_job_id(job_id: str | None) -> str:
    if job_id is None:
        raise HTTPException(status_code=422, detail="job_id is required")
    return job_id


#: A plist export of a tag's key is a few hundred bytes. 64 KiB is generous and
#: still bounds what an oversized body can cost before anything is parsed.
_MAX_PLIST_BYTES = 64 * 1024

#: Multipart framing (boundary markers, the two part headers, the 'name'
#: field) adds a small, bounded amount on top of the plist bytes themselves.
_MULTIPART_OVERHEAD_BYTES = 4 * 1024


def _reject_oversized_content_length(request: Request) -> None:
    """413 from the Content-Length header alone, before the body is parsed.

    A cheap short-circuit only: a well-formed, truthful header lets us
    refuse before anything is read. `read_bounded_form()` is the real
    guard -- it bounds the body as it streams in regardless of what this
    header says, or whether the client sent one at all (G1: a chunked or
    lying-length upload must not reach `request.form()` unbounded).
    """
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return
    try:
        declared = int(raw_length)
    except ValueError:
        return
    if declared > _MAX_PLIST_BYTES + _MULTIPART_OVERHEAD_BYTES:
        raise HTTPException(status_code=413, detail="plist too large")


def _parse_allow_overwrite(raw: object) -> bool:
    """The JSON bool, or the multipart form's string ("true"/"false").

    Anything else (missing, "false", a stray non-bool) keeps the strict
    web default: no overwrite unless the caller says so (CF-P2-19).
    """
    if isinstance(raw, bool):
        return raw
    return isinstance(raw, str) and raw.strip().lower() == "true"


async def _read_accessory_body(
    request: Request, settings
) -> tuple[str, Path | None, str | None, bool]:
    """(name, plist_path, private_key_b64, allow_overwrite) from whichever body shape arrived.

    FastAPI parses one body as form data or JSON, so Content-Type picks the
    branch. `allow_overwrite` defaults to False in both; the dashboard's
    "Replace existing" confirm is the only caller sending true (CF-P2-19).
    """
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        _reject_oversized_content_length(request)
        form = await read_bounded_form(request, _MAX_PLIST_BYTES + _MULTIPART_OVERHEAD_BYTES)
        raw_name = form.get("name")
        upload = form.get("plist")
        if not isinstance(raw_name, str) or upload is None or isinstance(upload, str):
            raise HTTPException(
                status_code=422, detail="multipart body requires 'name' and a 'plist' file"
            )
        if upload.size is not None and upload.size > _MAX_PLIST_BYTES:
            raise HTTPException(status_code=413, detail="plist too large")

        plist_bytes = await upload.read(_MAX_PLIST_BYTES + 1)
        # Checked on the bytes already read, before any write.
        if len(plist_bytes) > _MAX_PLIST_BYTES:
            raise HTTPException(status_code=413, detail="plist too large")
        plist_path = settings.state_dir / f".accessory-upload-{uuid.uuid4().hex}.plist"
        # 0600 BEFORE the key material is written, the same order save_account()
        # and add_accessory() use. state_dir is 0700, but a private key must not
        # rest in a default-mode file even for the length of one request.
        plist_path.touch(mode=0o600, exist_ok=False)
        plist_path.chmod(0o600)
        plist_path.write_bytes(plist_bytes)
        return raw_name, plist_path, None, _parse_allow_overwrite(form.get("allow_overwrite"))

    try:
        payload = await request.json()
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


def _require_apple_provider() -> None:
    """503 with the extra's own install hint, never a bare 500 or a traceback."""
    from findplus.providers.apple_findmy import is_available

    avail, hint = is_available()
    if not avail:
        raise HTTPException(status_code=503, detail=f"Apple provider not installed. {hint}")


def auth_status() -> dict[str, Any]:
    return build_auth_status()


def google_start(request: Request) -> dict[str, Any]:
    _require_origin_signal(request)
    try:
        job_id = start_google_auth(get_settings())
    except ChromeNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GoogleAuthAlreadyRunningError as exc:
        # JSONResponse, not `raise HTTPException`: the body must be flat,
        # and HTTPException would nest job_id under "detail".
        return JSONResponse(
            status_code=409,
            content={
                "detail": "A Google sign-in is already in progress.",
                "job_id": exc.job_id,
            },
        )
    return {"job_id": job_id}


def google_progress(job_id: str | None = Query(default=None)) -> dict[str, Any]:
    from findplus.cli.doctor import check_chrome

    progress = get_google_auth_progress(_require_job_id(job_id))
    if progress is None:
        raise HTTPException(status_code=404, detail="unknown or expired job_id")
    # Recomputed every call, never cached, so a "Chrome required" banner in
    # the dashboard clears itself the moment the user installs Chrome.
    return {**progress, "chrome_found": check_chrome().passed}


def apple_start(body: AppleStartBody, request: Request) -> dict[str, Any]:
    _require_origin_signal(request)
    _require_apple_provider()
    try:
        job_id = start_apple_auth(get_settings(), body.apple_id, body.password)
    except AppleAuthAlreadyRunningError as exc:
        # Flat, like google_start's 409, for the same reason.
        return JSONResponse(
            status_code=409,
            content={
                "detail": "An Apple sign-in is already in progress.",
                "job_id": exc.job_id,
            },
        )
    return {"job_id": job_id}


def apple_code(body: AppleCodeBody, request: Request) -> dict[str, Any]:
    _require_origin_signal(request)
    _require_apple_provider()
    try:
        apple_id = submit_apple_code(body.job_id, body.code, get_settings())
    except UnknownAppleJobError as exc:
        raise HTTPException(status_code=404, detail="unknown or expired job_id") from exc
    except InvalidAppleCodeError as exc:
        raise HTTPException(status_code=400, detail="invalid or expired code") from exc
    return {"state": "done", "message": f"Authenticated as {apple_id}."}


def apple_progress(job_id: str | None = Query(default=None)) -> dict[str, Any]:
    progress = get_apple_auth_progress(_require_job_id(job_id))
    if progress is None:
        raise HTTPException(status_code=404, detail="unknown or expired job_id")
    return progress


async def apple_accessories(request: Request) -> dict[str, Any]:
    # Deliberately NOT behind _require_origin_signal: specs/auth-ui.md §8
    # lists only the three sign-in starters, and this route is reachable
    # from headerless callers the way every other mutating route is. That is
    # safe against a cross-site <form> POST because OriginGuardMiddleware's
    # same_origin_problem() refuses a foreign Origin or Sec-Fetch-Site on
    # every mutating /api/ route already, and (blind cap B3) a foreign
    # Referer too when both of those are absent -- the one shape that used
    # to reach this handler unchecked. A headerless CLI/MCP request carries
    # none of the three and still passes.
    _require_apple_provider()
    settings = get_settings()
    # The CLI path reaches accessories.py after `_prep()` has made the
    # state dir; an HTTP request has not, and _accessories_dir() does not
    # create parents. 0700 for the same reason ensure_dirs() does it.
    settings.ensure_dirs()
    name, plist_path, private_key_b64, allow_overwrite = await _read_accessory_body(
        request, settings
    )
    try:
        record = add_accessory(
            name,
            settings,
            plist_path=plist_path,
            private_key_b64=private_key_b64,
            allow_overwrite=allow_overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        # The upload is a courier, not a record: the permanent 0600 copy is
        # add_accessory()'s. Removed whether it succeeded or raised.
        if plist_path is not None:
            plist_path.unlink(missing_ok=True)
    return {
        "device_id": record["device_id"],
        "name": record["name"],
        "kind": record["kind"],
        "added_at": record["added_at"],
    }


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["auth"])
    router.add_api_route("/auth/status", auth_status, methods=["GET"])
    router.add_api_route("/auth/google/start", google_start, methods=["POST"], status_code=202)
    router.add_api_route("/auth/google/progress", google_progress, methods=["GET"])
    router.add_api_route("/auth/apple/start", apple_start, methods=["POST"], status_code=202)
    router.add_api_route("/auth/apple/code", apple_code, methods=["POST"])
    router.add_api_route("/auth/apple/progress", apple_progress, methods=["GET"])
    router.add_api_route("/apple/accessories", apple_accessories, methods=["POST"], status_code=201)
    return router

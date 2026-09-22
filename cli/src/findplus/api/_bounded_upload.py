"""Bound a request body while it streams in, not after -- multipart or JSON.

Purpose    : `reject_oversized_content_length` below only refuses an
             oversized accessory upload when the client sends a truthful
             Content-Length header. A chunked request -- or one whose header
             understates the real body -- skips that check.
             For multipart, Starlette's MultiPartParser has no size limit of
             its own for a *file* part (unlike an ordinary form field, which
             its `max_part_size` argument already caps): it writes every
             byte of an uploaded file straight to a SpooledTemporaryFile
             with nothing to stop it. For JSON, `Request.json()` buffers the
             whole body into memory with no limit at all (CR-C-m4: a 2 MB
             JSON body was fully read before its 422 for a bad key). Both
             read functions here wrap the request's ASGI receive callable so
             every chunk is counted as it arrives, regardless of what the
             header claimed or whether one was sent at all.
Inputs     : A FastAPI Request whose body has not been read yet, and the
             byte limit the whole body must stay under.
Outputs    : The parsed FormData/JSON value, or HTTPException(413) raised as
             soon as the running total crosses the limit, before the rest of
             the body is read.
Constraints: Must run before any other code reads the request body
             (`.stream()` / `.form()` / `.json()`) -- Starlette lets a body
             be consumed only once.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from starlette.datastructures import FormData


class _BodyTooLargeError(Exception):
    """Internal marker: the wrapped receive() saw more bytes than the limit."""


def _bounded_receive(receive, limit: int):
    total = 0

    async def wrapped():
        nonlocal total
        message = await receive()
        if message.get("type") == "http.request":
            total += len(message.get("body", b""))
            if total > limit:
                raise _BodyTooLargeError()
        return message

    return wrapped


def _apply_receive_limit(request: Request, limit: int) -> None:
    request._receive = _bounded_receive(request._receive, limit)


async def read_bounded_form(request: Request, limit: int) -> FormData:
    """Parse `request`'s multipart body, refusing anything past `limit` bytes
    as they arrive -- independent of Content-Length, present or not."""
    _apply_receive_limit(request, limit)
    try:
        return await request.form()
    except _BodyTooLargeError as exc:
        raise HTTPException(status_code=413, detail="plist too large") from exc


async def read_bounded_json(request: Request, limit: int) -> Any:
    """Parse `request`'s JSON body, refusing anything past `limit` bytes as
    they arrive -- independent of Content-Length, present or not (CR-C-m4)."""
    _apply_receive_limit(request, limit)
    try:
        return await request.json()
    except _BodyTooLargeError as exc:
        raise HTTPException(status_code=413, detail="request body too large") from exc


def reject_oversized_content_length(request: Request, limit: int) -> None:
    """413 from the Content-Length header alone, before the body is parsed.

    A cheap short-circuit only: a well-formed, truthful header lets us
    refuse before anything is read. `read_bounded_form`/`read_bounded_json`
    are the real guard -- they bound the body as it streams in regardless of
    what this header says, or whether the client sent one at all (G1: a
    chunked or lying-length upload must not reach `request.form()`/`.json()`
    unbounded).
    """
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return
    try:
        declared = int(raw_length)
    except ValueError:
        return
    if declared > limit:
        raise HTTPException(status_code=413, detail="plist too large")

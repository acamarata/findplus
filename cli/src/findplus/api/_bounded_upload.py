"""Bound a multipart request body while it streams in, not after.

Purpose    : `_reject_oversized_content_length` in routes_auth.py only
             refuses an oversized accessory upload when the client sends a
             truthful Content-Length header. A chunked request -- or one
             whose header understates the real body -- skips that check,
             and Starlette's MultiPartParser has no size limit of its own
             for a *file* part (unlike an ordinary form field, which its
             `max_part_size` argument already caps): it writes every byte
             of an uploaded file straight to a SpooledTemporaryFile with
             nothing to stop it. This wraps the request's ASGI receive
             callable so every chunk is counted as it arrives, regardless
             of what the header claimed or whether one was sent at all.
Inputs     : A FastAPI Request whose body has not been read yet, and the
             byte limit the whole body (multipart framing plus the plist
             itself) must stay under.
Outputs    : The parsed FormData, or HTTPException(413) raised as soon as
             the running total crosses the limit, before the rest of the
             body is read.
Constraints: Must run before any other code reads the request body
             (`.stream()` / `.form()` / `.json()`) -- Starlette lets a body
             be consumed only once.
"""

from __future__ import annotations

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


async def read_bounded_form(request: Request, limit: int) -> FormData:
    """Parse `request`'s multipart body, refusing anything past `limit` bytes
    as they arrive -- independent of Content-Length, present or not."""
    request._receive = _bounded_receive(request._receive, limit)
    try:
        return await request.form()
    except _BodyTooLargeError as exc:
        raise HTTPException(status_code=413, detail="plist too large") from exc

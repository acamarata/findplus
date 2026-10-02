"""Shared error mapping for the people routes (routes_people*.py).

Purpose    : One mapping from the people/groups repo's ValueError text to HTTP:
             "not found" -> 404, "already exists" / "already belongs to" -> 409,
             anything else -> 422; a UNIQUE IntegrityError -> 409.
Outputs    : map_value_error(); run_write() runs one repo call in one
             transaction and commits only when it returns.
Constraints: No route registration here.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from findplus.db.session import session_scope


def map_value_error(exc: ValueError) -> HTTPException:
    text = str(exc)
    if "not found" in text:
        return HTTPException(status_code=404, detail=text)
    conflict = "already exists" in text or "already belongs to" in text
    return HTTPException(status_code=409 if conflict else 422, detail=text)


def run_write(fn, *args, **kwargs):
    """Run `fn(session, *args)` in one transaction, mapping its errors to HTTP."""
    with session_scope() as s:
        try:
            result = fn(s, *args, **kwargs)
        except ValueError as exc:
            s.rollback()
            raise map_value_error(exc) from exc
        except IntegrityError as exc:
            s.rollback()
            if "UNIQUE" not in str(exc):
                raise
            raise HTTPException(status_code=409, detail="that name already exists") from exc
        s.commit()
        return result

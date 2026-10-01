"""Which API paths stay reachable while the app lock is on.

Purpose : The lock middleware (api/__init__.py) 401s every `/api/` path except
          these two sets. Split out to keep that module under the 300-line cap.
Outputs : `_PUBLIC`, `_STATE_GATED` (frozensets of exact request paths).
Constraints: `findplus.api._PUBLIC` and `._STATE_GATED` stay importable (re-exported).
"""

from __future__ import annotations

#: Endpoints reachable while the app is locked. Everything else 401s.
#: The lock is enforced HERE, server-side — hiding the UI would leave the data
#: one `curl` away. Corrected to the 8-path set from specs/api-contract.md
#: (renamed from the legacy 3-entry _UNGATED_PATHS, which was under-enforced).
#: `/static/*` and `/` were dead entries: this middleware only inspects paths
#: that start with `/api/`, so neither could ever be compared against, and a
#: literal `"/static/*"` never equals a real request path anyway.
_PUBLIC = frozenset(
    {
        "/api/health",
        "/api/version",
        "/api/lock/status",
        "/api/lock/unlock",
        "/api/lock/lock",
        "/api/lock/requirements",
    }
)


#: Chrome-helper ingest routes: the extension has no dashboard cookie, so a
#: locked app would time its sign-in out. Each handler needs the pinned
#: extension origin and a single-use state minted by an unlocked session, and
#: none returns location data.
_STATE_GATED = frozenset(
    {
        "/api/auth/google/helper/token",
        "/api/auth/google/helper/unlock",
        # The begin page (also cookie-less, in the user's own Chrome) reports the
        # helper is installed. It only sets a "helper detected" hint.
        "/api/auth/google/helper/seen",
    }
)

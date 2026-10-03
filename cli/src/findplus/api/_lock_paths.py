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
        # The desktop shell installs a staged update while the app is locked
        # (idle is when it is safe to restart). The body names no paths or places.
        "/api/update/status",
    }
)


#: Chrome-helper ingest routes: the extension has no dashboard cookie, so a
#: locked app would time its sign-in out. token and unlock need the pinned
#: extension origin and a single-use state minted by an unlocked session; `seen`
#: checks neither (it only sets a UI hint). None returns location data.
_STATE_GATED = frozenset(
    {
        "/api/auth/google/helper/token",
        "/api/auth/google/helper/unlock",
        # The begin page (also cookie-less, in the user's own Chrome) reports the
        # helper is installed. It only sets a "helper detected" hint.
        "/api/auth/google/helper/seen",
        # The desktop shell's in-app sign-in window posts these with no cookie.
        # Each needs the pinned shell Origin and header AND a single-use state
        # minted by an unlocked session (_routes_auth_google_native.py).
        "/api/auth/google/native/token",
        "/api/auth/google/native/unlock",
        "/api/auth/google/native/event",
        "/api/auth/google/native/classify",
        # Backs up and gets a staged update ready; needs the shell's own header
        # (routes_update.py), so no web page can start an install.
        "/api/update/apply",
    }
)

"""The Chrome-helper Google flow: begin pages, success page, and the two
ingest endpoints the helper extension posts to.

Purpose    : Give Find+ a plain "Sign in with Google" experience via the
             open-source helper extension (browser-helper/). The daemon opens a
             127.0.0.1 begin page in the user's own Chrome; the helper hands the
             page a single-use state, marks it installed and redirects to
             Google; the helper's service worker posts the sign-in token (or the
             unlock vault keys) back here with the pinned extension origin and
             that state. The daemon exchanges/stores exactly as the other flows
             do and never stores or logs the token or keys.
Constraints: The two ingest endpoints require the pinned extension origin AND a
             valid single-use state (helper_state.py); everything else is 403.
             The begin/success pages are plain daemon-served HTML with no inline
             script or style (the app CSP forbids both); the redirect and the
             not-installed fallback live in /static/app/helper-begin.js.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from findplus.providers.google_findhub import helper_state
from findplus.providers.google_findhub.open_signin import (
    EMBEDDED_SETUP_URL,
    BrowserOpenError,
    open_sign_in_page,
)
from findplus.providers.google_findhub.token_signin import (
    TokenRejectedError,
    TokenSignInError,
    sign_in_with_oauth_token,
)
from findplus.providers.google_findhub.unlock import SharedKeyParseError, store_vault_keys


class HelperTokenBody(BaseModel):
    state: str = ""
    oauth_token: Any = ""


class HelperUnlockBody(BaseModel):
    state: str = ""
    vault_keys: Any = ""


class HelperSeenBody(BaseModel):
    state: str = ""


def _bound_port(request: Request) -> int:
    return int(request.app.state.bound_port)


def _begin_url(request: Request, path: str, state: str) -> str:
    # Always 127.0.0.1 (not localhost): the extension's content-script match and
    # host permission are pinned to 127.0.0.1.
    return f"http://127.0.0.1:{_bound_port(request)}{path}?state={state}"


def _open(request: Request, path: str, kind: str) -> dict[str, Any]:
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    state = helper_state.create_state(kind)
    try:
        browser = open_sign_in_page(_begin_url(request, path, state))
    except BrowserOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"browser": browser}


def helper_begin(request: Request) -> dict[str, Any]:
    return _open(request, "/auth/google/begin", helper_state.KIND_SIGNIN)


def helper_unlock_begin(request: Request) -> dict[str, Any]:
    return _open(request, "/auth/google/unlock/begin", helper_state.KIND_UNLOCK)


def _require_extension_origin(request: Request) -> None:
    if not helper_state.is_allowed_extension_origin(request.headers.get("origin")):
        raise HTTPException(status_code=403, detail="not the Find+ helper")


def helper_token(body: HelperTokenBody, request: Request) -> dict[str, Any]:
    _require_extension_origin(request)
    if not helper_state.consume_state(helper_state.KIND_SIGNIN, body.state):
        raise HTTPException(status_code=403, detail="invalid or expired state")
    try:
        # Empty email on purpose: Google's response supplies it (vendored flow).
        account = sign_in_with_oauth_token("", body.oauth_token, require_email=False)
    except TokenRejectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except TokenSignInError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"state": "done", "account": account}


def helper_unlock(body: HelperUnlockBody, request: Request) -> dict[str, Any]:
    _require_extension_origin(request)
    if not helper_state.consume_state(helper_state.KIND_UNLOCK, body.state):
        raise HTTPException(status_code=403, detail="invalid or expired state")
    try:
        store_vault_keys(body.vault_keys)
    except SharedKeyParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"state": "done"}


def helper_seen(body: HelperSeenBody) -> dict[str, Any]:
    # Called by the begin page itself (same origin), so the standard guard
    # already vetted it. Just records the "helper installed" hint.
    helper_state.mark_seen()
    return {"ok": True}


def helper_reveal(request: Request) -> dict[str, Any]:
    """Copy the extension to a stable folder and reveal it in the file manager."""
    from findplus.api.routes_auth import _require_origin_signal
    from findplus.config import get_settings
    from findplus.providers.google_findhub.browser_helper import reveal_helper

    _require_origin_signal(request)
    try:
        path = reveal_helper(get_settings())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"path": str(path)}


def helper_open_extensions(request: Request) -> dict[str, Any]:
    """Open chrome://extensions in the user's Google Chrome (their explicit ask)."""
    from findplus.api.routes_auth import _require_origin_signal
    from findplus.providers.google_findhub.browser_helper import open_chrome_extensions

    _require_origin_signal(request)
    return {"opened": open_chrome_extensions()}


# --------------------------------------------------------------------- pages
_BEGIN_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Find+ sign-in</title>
<link rel="stylesheet" href="/static/helper.css">
</head><body>
<main class="fp-helper" data-fp-begin data-fp-target="{target}" data-fp-state="{state}">
  <h1>Connecting to Google</h1>
  <p class="fp-helper-wait" data-fp-wait>Starting the Find+ helper...</p>
  <section class="fp-helper-install" data-fp-install hidden>
    <h2>Add the Find+ helper to Chrome (one time)</h2>
    <p>The Find+ helper for Chrome is not installed yet. In Find+, open
      Settings then Sign-in and use "Show helper folder", then in Chrome open
      <code>chrome://extensions</code>, turn on Developer mode, click Load
      unpacked, and choose that folder. Then start sign-in again.</p>
  </section>
</main>
<script type="module" src="/static/app/helper-begin.js"></script>
</body></html>
"""

_SUCCESS_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Find+</title><link rel="stylesheet" href="/static/helper.css">
</head><body><main class="fp-helper"><h1>Signed in</h1>
<p>You can close this tab. Find+ continues on its own.</p></main></body></html>
"""


def _begin_page(target: str, state: str) -> HTMLResponse:
    return HTMLResponse(
        _BEGIN_TEMPLATE.format(
            target=html.escape(target, quote=True),
            state=html.escape(state, quote=True),
        )
    )


def begin_page(state: str = Query(default="")) -> HTMLResponse:
    return _begin_page(EMBEDDED_SETUP_URL, state)


def unlock_begin_page(state: str = Query(default="")) -> HTMLResponse:
    from findplus.providers.google_findhub.bootstrap import ensure_gfmt_importable

    ensure_gfmt_importable()
    from KeyBackup.shared_key_request import get_security_domain_request_url

    return _begin_page(get_security_domain_request_url(), state)


def success_page() -> HTMLResponse:
    return HTMLResponse(_SUCCESS_PAGE)


def register(router) -> None:
    """Register the helper ingest POSTs on the /api auth router (routes_auth)."""
    router.add_api_route(
        "/auth/google/helper/begin", helper_begin, methods=["POST"], status_code=202
    )
    router.add_api_route(
        "/auth/google/helper/unlock-begin", helper_unlock_begin, methods=["POST"], status_code=202
    )
    router.add_api_route("/auth/google/helper/token", helper_token, methods=["POST"])
    router.add_api_route("/auth/google/helper/unlock", helper_unlock, methods=["POST"])
    router.add_api_route("/auth/google/helper/seen", helper_seen, methods=["POST"])
    router.add_api_route("/auth/google/helper/reveal", helper_reveal, methods=["POST"])
    router.add_api_route(
        "/auth/google/helper/open-extensions", helper_open_extensions, methods=["POST"]
    )


def build_pages_router():
    """The plain begin/success HTML pages, served OUTSIDE /api (the user's own
    Chrome opens them with no session cookie, so they must not be lock-gated)."""
    from fastapi import APIRouter

    router = APIRouter(tags=["auth"])
    router.add_api_route("/auth/google/begin", begin_page, methods=["GET"])
    router.add_api_route("/auth/google/unlock/begin", unlock_begin_page, methods=["GET"])
    router.add_api_route("/auth/google/success", success_page, methods=["GET"])
    return router

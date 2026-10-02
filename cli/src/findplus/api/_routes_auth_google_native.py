"""HTTP for the in-app Google sign-in window (spec in-app-login.md §2.2).

Purpose    : The desktop shell (or the dashboard card, which then hands the
             answer to the shell) begins a flow; the shell posts the token, the
             unlock keys, window events and blocked-page reports back over
             loopback; the card polls progress and may cancel. The logic lives in
             providers/google_findhub/native_flow.py; this maps it to HTTP.
Inputs     : JSON bodies; the Origin and X-FindPlus-Client headers.
Outputs    : JSON; refusals are `{"detail": <plain words>, "code": <word>}`.
Constraints: begin and cancel carry routes_auth's Origin/Sec-Fetch-Site guard and
             the app lock, like every sign-in starter. The four shell ingest
             routes skip the lock (_lock_paths._STATE_GATED) and instead need the
             pinned shell headers AND a live single-use state, like the Chrome
             helper's ingest routes. Body fields are `Any` so FastAPI never
             answers a 422 that quotes the token or the keys back.
             Contract: .github/docs/specs/in-app-login-contract.md.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from findplus.providers.google_findhub import native_flow, native_progress
from findplus.providers.google_findhub.native_flow import NativeFlowError

#: The header the shell sends on every ingest post, with exactly this value.
SHELL_HEADER = "X-FindPlus-Client"
SHELL_HEADER_VALUE = "signin-window"

PREFIX = "/api/auth/google/native"
#: Shell-only posts: no dashboard cookie, own gate (pinned headers + state).
NATIVE_INGEST_PATHS = frozenset(
    {f"{PREFIX}/token", f"{PREFIX}/unlock", f"{PREFIX}/event", f"{PREFIX}/classify"}
)


class BeginBody(BaseModel):
    mode: Any = "signin"


class TokenBody(BaseModel):
    state: Any = ""
    oauth_token: Any = ""


class UnlockBody(BaseModel):
    state: Any = ""
    vault_keys: Any = ""
    account_hint: Any = None


class EventBody(BaseModel):
    state: Any = ""
    event: Any = ""
    reason: Any = None


class ClassifyBody(BaseModel):
    state: Any = ""
    host: Any = ""
    path: Any = ""
    title_class: Any = "unknown"


def _refusal(exc: NativeFlowError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.message, "code": exc.code})


def shell_origin(request: Request) -> str:
    """The one Origin the shell sends: the daemon's own 127.0.0.1 address."""
    return f"http://127.0.0.1:{request.app.state.bound_port}"


def _require_shell(request: Request) -> None:
    if (
        request.headers.get("origin") != shell_origin(request)
        or request.headers.get(SHELL_HEADER) != SHELL_HEADER_VALUE
    ):
        raise NativeFlowError(403, "bad_client", "Not the Find+ sign-in window.")


def native_begin(body: BeginBody, request: Request) -> Any:
    """Start an in-app sign-in (or unlock): a single-use state and the window's settings."""
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    if not request.headers.get("origin"):
        # The shell and the dashboard both send their 127.0.0.1 Origin;
        # OriginGuardMiddleware has already refused any other one.
        return _refusal(NativeFlowError(403, "bad_client", "Missing Origin."))
    try:
        return native_flow.begin(body.mode)
    except NativeFlowError as exc:
        return _refusal(exc)


def native_token(body: TokenBody, request: Request) -> Any:
    """The shell hands over Google's sign-in value once; Find+ exchanges it, never stores it."""
    try:
        _require_shell(request)
        return native_flow.submit_token(body.state, body.oauth_token)
    except NativeFlowError as exc:
        return _refusal(exc)


def native_unlock(body: UnlockBody, request: Request) -> Any:
    """The shell relays the unlock page's vault keys; Find+ keeps only the location key."""
    try:
        _require_shell(request)
        return native_flow.submit_unlock(body.state, body.vault_keys, body.account_hint)
    except NativeFlowError as exc:
        return _refusal(exc)


def native_event(body: EventBody, request: Request) -> Any:
    """The window opened, is waiting, was blocked, closed or failed."""
    try:
        _require_shell(request)
        return native_flow.record_event(body.state, body.event, body.reason)
    except NativeFlowError as exc:
        return _refusal(exc)


def native_classify(body: ClassifyBody, request: Request) -> Any:
    """Did Google block the window? The shell sends a host, a path and a title class only."""
    try:
        _require_shell(request)
        return native_flow.classify_report(body.state, body.host, body.path, body.title_class)
    except NativeFlowError as exc:
        return _refusal(exc)


def native_progress_route() -> dict[str, Any]:
    """Where the in-app sign-in stands; the dashboard card polls this."""
    return native_progress.snapshot()


def native_cancel(request: Request) -> dict[str, Any]:
    """Cancel the in-app sign-in: its state stops working at once."""
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    return native_flow.cancel()


def register(router) -> None:
    """Register on routes_auth's "/api" router."""
    base = "/auth/google/native"
    router.add_api_route(f"{base}/begin", native_begin, methods=["POST"])
    router.add_api_route(f"{base}/token", native_token, methods=["POST"])
    router.add_api_route(f"{base}/unlock", native_unlock, methods=["POST"])
    router.add_api_route(f"{base}/event", native_event, methods=["POST"])
    router.add_api_route(f"{base}/classify", native_classify, methods=["POST"])
    router.add_api_route(f"{base}/progress", native_progress_route, methods=["GET"])
    router.add_api_route(f"{base}/cancel", native_cancel, methods=["POST"])

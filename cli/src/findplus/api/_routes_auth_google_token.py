"""The main-Chrome Google sign-in routes: open the page, then exchange the token.

Purpose    : `POST /api/auth/google/open` opens Google's EmbeddedSetup page in
             the user's own Chrome; `POST /api/auth/google/token` takes the
             `oauth_token` cookie they copied from it and signs Find+ in
             (providers/google_findhub/{open_signin,token_signin}.py). The
             automatic separate-window flow stays on /auth/google/start.
Inputs     : No body for /open; `{email, oauth_token}` for /token.
Outputs    : /open -> `{browser: "chrome"|"default", url}`; /token -> `{state:
             "done", account, message}`. Failures are `{detail}` in plain words.
Constraints: Both routes carry routes_auth's Origin/Sec-Fetch-Site guard, like
             every other sign-in POST. The token is never logged or echoed:
             the body fields accept any JSON value and default to "", so
             FastAPI never raises its own 422 that would quote the body back.
             The exchange blocks, so it runs in the threadpool and carries its
             own timeout (token_signin.EXCHANGE_TIMEOUT_SECONDS).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from findplus.providers.google_findhub.open_signin import (
    EMBEDDED_SETUP_URL,
    BrowserOpenError,
    open_sign_in_page,
)
from findplus.providers.google_findhub.token_signin import (
    GoogleUnreachableError,
    InvalidInputError,
    TokenRejectedError,
    TokenSignInError,
    sign_in_with_oauth_token,
)


class GoogleTokenBody(BaseModel):
    """The Google email and the oauth_token cookie value copied from Chrome."""

    # `Any` at runtime, "string" in the schema, on purpose: FastAPI's own 422
    # for a wrongly typed field quotes the submitted value back, which here
    # would be the token. token_signin's clean_email()/clean_oauth_token()
    # check the types themselves and answer in words.
    email: Any = Field(
        "", description="The Google email you signed in with.", json_schema_extra={"type": "string"}
    )
    oauth_token: Any = Field(
        "",
        description="The Value of the oauth_token cookie. Starts with oauth2_4/.",
        json_schema_extra={"type": "string"},
    )


def _status_for(exc: TokenSignInError) -> int:
    if isinstance(exc, InvalidInputError):
        return 422
    if isinstance(exc, TokenRejectedError):
        return 400
    if isinstance(exc, GoogleUnreachableError):
        return 502
    return 500


def google_open(request: Request) -> dict[str, Any]:
    """Open Google's sign-in page (EmbeddedSetup) in the user's own Chrome.

    A plain `def`, so FastAPI runs it in the threadpool: macOS `open` waits
    for LaunchServices.
    """
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    try:
        browser = open_sign_in_page()
    except BrowserOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"browser": browser, "url": EMBEDDED_SETUP_URL}


async def google_token(body: GoogleTokenBody, request: Request) -> dict[str, Any]:
    """Exchange a pasted `oauth_token` for a Find Hub session."""
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    try:
        account = await run_in_threadpool(sign_in_with_oauth_token, body.email, body.oauth_token)
    except TokenSignInError as exc:
        raise HTTPException(status_code=_status_for(exc), detail=str(exc)) from None
    return {"state": "done", "account": account, "message": f"Authenticated as {account}."}

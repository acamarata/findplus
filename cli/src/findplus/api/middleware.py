"""Host, origin and response-header guards for the local API.

Purpose    : Stop a page served from another origin from reaching this daemon,
             and stop a DNS name that resolves to 127.0.0.1 (DNS rebinding)
             from being used to drive it through the victim's own browser.
             Hostname alone is not enough for the Host/Origin checks: they
             also pin the configured port, so a rebound page that carries
             the right loopback name but the wrong (or no) port still fails.
Inputs     : The Host, Origin, Sec-Fetch-Site and Referer request headers.
Outputs    : 421 for a foreign or wrong-port Host, 403 for a foreign Origin,
             a cross-site mutation, or a mutation whose only origin signal is
             a foreign Referer, and the three response headers every
             dashboard response carries.
Constraints:
    - Registered OUTSIDE SessionAuthMiddleware so a rebinding attempt is
      refused before the lock, the routers or the static mount see it.
    - Non-browser callers (the CLI, the MCP server, curl) send no Origin, no
      Sec-Fetch-Site and no Referer, so they pass. That is deliberate: anyone
      who can run a local process already has the database file, and the
      guard exists to stop a REMOTE page, not a local user.
    - The Tauri shell loads http://127.0.0.1:8647/ in an external webview, so
      its requests are same-origin; the splash window's tauri:// origin is
      allowed explicitly.
    - The Referer fallback (blind cap B3) exists for a route like
      POST /api/apple/accessories that is deliberately not behind
      _require_origin_signal (routes_auth.py) so headerless CLI/MCP requests
      still work: an old-style cross-site <form> POST can omit both Origin
      and Sec-Fetch-Site while still carrying a Referer, and this is the one
      place that shape is checked, for every mutating /api/ route at once.
"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

__all__ = [
    "CONTENT_SECURITY_POLICY",
    "OriginGuardMiddleware",
    "SecurityHeadersMiddleware",
    "is_allowed_host",
    "is_allowed_origin",
    "same_origin_problem",
]

#: Host header values this daemon answers to, on top of its own bound host.
LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: The desktop shell's own protocol origins (macOS uses tauri://, Windows
#: https://tauri.localhost). The main window is an external webview on
#: http://127.0.0.1:8647 and so is already same-origin.
TAURI_ORIGINS = frozenset({"tauri://localhost", "https://tauri.localhost"})

#: Sec-Fetch-Site values a same-document or address-bar request can carry.
SAME_SITE_FETCH_VALUES = frozenset({"same-origin", "none"})

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Leaflet and its stylesheet are vendored under /static, so 'self' covers
#: every script and style. Only the OSM tile host is reachable for images,
#: which is exactly what index.html already discloses to the user.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' https://tile.openstreetmap.org data:; "
    "frame-ancestors 'none'"
)

_FOREIGN_HOST_DETAIL = (
    "This daemon only answers to 127.0.0.1 and localhost on its own port. "
    "A request arriving under another hostname or port is refused."
)
_FOREIGN_ORIGIN_DETAIL = "This request came from another origin and was refused."
_CROSS_SITE_DETAIL = "This request was initiated by another site and was refused."


def _hostname(host_header: str) -> str:
    """The hostname part of a Host header, port removed, `[::1]` kept
    bracketed, and a single trailing dot (the absolute-FQDN form a browser
    or curl may send, e.g. `localhost.`) stripped before the allowlist
    check ever compares it (G4) -- DNS treats the trailing dot as a no-op,
    so `localhost.` and `127.0.0.1.` name the same host as their bare form.
    """
    value = host_header.strip()
    if value.startswith("["):
        end = value.find("]")
        return value if end == -1 else value[: end + 1]
    if value.count(":") == 1:
        value = value.rsplit(":", 1)[0]
    return value[:-1] if value.endswith(".") else value


def _host_port(host_header: str) -> int | None:
    """The port carried by a Host header, or None when the header names no port.

    A bare Host (no `:port`) is what a real browser sends only when it means
    the scheme's default port (80 for http), which this daemon never binds
    to -- so the caller treats "no port" as "port 80", not as "any port".
    A trailing segment that isn't a plain integer (`:abc`, a truncated
    bracket) is not a port a real client would ever send, so it is treated
    the same as absent rather than guessed at.
    """
    value = host_header.strip()
    if value.startswith("["):
        end = value.find("]")
        rest = value[end + 1 :] if end != -1 else ""
    else:
        rest = value[value.rfind(":") :] if value.count(":") == 1 else ""
    if not rest.startswith(":"):
        return None
    try:
        return int(rest[1:])
    except ValueError:
        return None


def is_allowed_host(host_header: str | None, configured_host: str, configured_port: int) -> bool:
    """True when the Host header names this machine, on this exact port.

    Checking the hostname alone is not enough: DNS rebinding only changes
    which IP a name resolves to, not which port the attacker's page asks
    for, but nothing stops the page from putting a *different* loopback
    port in the URL either -- and this daemon only ever answers on one. A
    bare Host with no `:port` is accepted only when the configured port
    is 80 (the implied default for http), which findplus never uses.
    """
    if not host_header:
        return False
    name = _hostname(host_header).lower()
    configured = configured_host.strip().lower()
    if name not in LOOPBACK_HOSTNAMES and name not in {configured, f"[{configured}]"}:
        return False
    port = _host_port(host_header)
    return port == configured_port if port is not None else configured_port == 80


def _is_loopback_hostname(host: str) -> bool:
    """True only for a real loopback address or `localhost`.

    A prefix test on "127." would accept `127.0.0.1.evil.com`, which is an
    ordinary domain an attacker can register and point anywhere, so the
    address is parsed rather than string-matched.
    """
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _bracketed_ipv6(url: str) -> str:
    """Bracket a bare IPv6 host before parsing, e.g. `http://::1:8647` ->
    `http://[::1]:8647` (C-m1). `Settings.base_url`/`_bound_base_url` build
    an f-string from the configured host with no bracketing of their own, so
    `FINDPLUS_HOST=::1` (a loopback address the Host guard already accepts)
    produces exactly this unbracketed shape. urlsplit then reads the extra
    colons as more host:port separators and `.port` raises ValueError --
    turning a same-origin check into a 500 instead of a refusal. Anything
    already bracketed, or without enough colons to be IPv6, passes through.
    """
    scheme, sep, authority = url.partition("://")
    if not sep or authority.startswith("[") or authority.count(":") < 2:
        return url
    host, _, port = authority.rpartition(":")
    if not port.isdigit():
        return url
    return f"{scheme}://[{host}]:{port}"


def _port_of(url: str) -> int | None:
    """The port a URL implies: explicit, or the scheme's default (80/443);
    None when the authority cannot be parsed at all -- the caller then
    refuses the request instead of raising (C-m1)."""
    parts = urlsplit(_bracketed_ipv6(url))
    try:
        port = parts.port
    except ValueError:
        return None
    if port is not None:
        return port
    return 443 if parts.scheme == "https" else 80


def is_allowed_origin(origin: str, base_url: str) -> bool:
    """True for our own base URL, a loopback origin on our own port, and the
    desktop shell.

    A loopback IP at some OTHER port used to be accepted outright. That is
    still a real machine, but not necessarily this daemon's own page -- any
    other local process bound to a different port could carry that origin,
    so only the configured port is trusted, same as the Host check above.
    """
    if origin in TAURI_ORIGINS or origin == base_url:
        return True
    parts = urlsplit(_bracketed_ipv6(origin))
    if parts.scheme not in {"http", "https"}:
        return False
    if not _is_loopback_hostname((parts.hostname or "").lower()):
        return False
    origin_port, base_port = _port_of(origin), _port_of(base_url)
    return origin_port is not None and origin_port == base_port


def _origin_of(url: str) -> str:
    """`scheme://netloc` from a full URL, so a Referer can be checked like an Origin.

    Falls back to the raw value when it has neither: is_allowed_origin's own
    urlsplit then sees no http/https scheme and refuses it, which is the
    safe default for a header shaped like nothing valid.
    """
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else url


def _bound_base_url(request: Request) -> str:
    """`http://host:port` for the address this app was actually bound to.

    `app.state.bound_host`/`bound_port` are set once by `create_app()`
    (closeout C-M1) -- never `get_settings()` re-read per request, so a
    `findplus config set port ...` written while this daemon is already
    running cannot move the port the guard checks against out from under
    the bind it is actually serving.
    """
    state = request.app.state
    return f"http://{state.bound_host}:{state.bound_port}"


def same_origin_problem(request: Request) -> str | None:
    """The reason to refuse this request, or None when it looks same-origin.

    Shared by the middleware and by the first-time `POST /api/settings/pin`
    route, which applies it even to a request the middleware would let past.
    """
    base_url = _bound_base_url(request)
    origin = request.headers.get("origin")
    if origin and not is_allowed_origin(origin, base_url):
        return _FOREIGN_ORIGIN_DETAIL
    site = request.headers.get("sec-fetch-site")
    if request.method in _MUTATING_METHODS and site and site not in SAME_SITE_FETCH_VALUES:
        return _CROSS_SITE_DETAIL
    if request.method in _MUTATING_METHODS and not origin and not site:
        # Neither of the two usual signals is present. A plain non-browser
        # client (the CLI, the MCP server) sends no Referer either and passes
        # here unaffected; an old-style cross-site <form> POST -- exactly the
        # shape a route like POST /api/apple/accessories is reachable to
        # because it skips _require_origin_signal on purpose -- still carries
        # one, and that is what this closes (blind cap B3).
        referer = request.headers.get("referer")
        if referer and not is_allowed_origin(_origin_of(referer), base_url):
            return _FOREIGN_ORIGIN_DETAIL
    return None


class OriginGuardMiddleware(BaseHTTPMiddleware):
    """Refuse foreign Host headers outright, and foreign origins on /api/."""

    async def dispatch(self, request: Request, call_next):
        state = request.app.state
        if not is_allowed_host(request.headers.get("host"), state.bound_host, state.bound_port):
            return JSONResponse(status_code=421, content={"detail": _FOREIGN_HOST_DETAIL})
        if request.url.path.startswith("/api/"):
            problem = same_origin_problem(request)
            if problem is not None:
                return JSONResponse(status_code=403, content={"detail": problem})
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add the CSP and the two sniffing/framing headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

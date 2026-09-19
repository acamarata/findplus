"""HTTP client the MCP server uses to talk to the local Find+ daemon.

Purpose    : Isolate every httpx call behind one class so MCP tool functions
             contain zero HTTP code, per ADR-P1-06.
Inputs     : Daemon base URL; an in-process session cookie set by unlock().
Outputs    : Parsed JSON dicts (401/ConnectError mapped to the standard MCP
             error shape), or (text, status) for the export tool.
Constraints: Loopback only (enforced by the daemon); no retries; 30s/60s
             timeouts.
"""

from __future__ import annotations

import httpx

from findplus.honesty import FIND_HUB

_LOCKED = {"error": {"code": "locked", "message": "Find+ is locked", "hint": "call unlock(pin)"}}
_DAEMON_DOWN = {
    "error": {"code": "daemon_down", "message": "daemon not running", "hint": "run findplus start"}
}


class DaemonClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8647") -> None:
        self._base_url = base_url.rstrip("/")
        self._session_cookie: str | None = None
        self._notice: str | None = None

    def _headers(self) -> dict[str, str]:
        if self._session_cookie:
            return {"Cookie": f"findplus_session={self._session_cookie}"}
        return {}

    async def _send(self, method: str, path: str, timeout: float, **kw: object) -> httpx.Response:
        async with httpx.AsyncClient() as c:
            return await c.request(
                method, self._base_url + path, headers=self._headers(), timeout=timeout, **kw
            )

    async def _request(
        self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None
    ) -> dict:
        try:
            r = await self._send(method, path, 30.0, params=params, json=json_body)
        except httpx.ConnectError:
            return _DAEMON_DOWN
        if r.status_code == 401:
            return _LOCKED
        return r.json()

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: dict | None = None) -> dict:
        return await self._request("POST", path, json_body=body)

    async def put(self, path: str, body: dict | None = None) -> dict:
        return await self._request("PUT", path, json_body=body)

    async def delete(self, path: str) -> dict:
        return await self._request("DELETE", path)

    async def post_with_cookie(
        self, path: str, body: dict | None = None
    ) -> tuple[dict, str | None]:
        try:
            r = await self._send("POST", path, 30.0, json=body)
        except httpx.ConnectError:
            return _DAEMON_DOWN, None
        cookie_val = r.cookies.get("findplus_session")
        if r.status_code == 401:
            return _LOCKED, None
        return r.json(), cookie_val

    async def get_text(self, path: str, params: dict | None = None) -> tuple[str, int]:
        try:
            r = await self._send("GET", path, 60.0, params=params)
        except httpx.ConnectError:
            return "", 503
        return r.text, r.status_code

    @property
    def session_cookie(self) -> str | None:
        return self._session_cookie

    def set_session_cookie(self, value: str) -> None:
        self._session_cookie = value

    def clear_session_cookie(self) -> None:
        self._session_cookie = None

    async def get_notice(self) -> str:
        if self._notice is None:
            cfg = await self.get("/api/config")
            if "error" in cfg:
                return FIND_HUB
            self._notice = cfg["notices"]["find_hub"]
        return self._notice

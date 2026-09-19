"""HTTP client the MCP server uses to talk to the local Find+ daemon.

Purpose    : Isolate every httpx call behind one class so MCP tool functions
             contain zero HTTP code, per ADR-P1-06.
Inputs     : Daemon base URL; an in-process session cookie set by unlock().
Outputs    : Parsed JSON dicts (every non-2xx status and every transport
             failure mapped to the standard MCP error shape by
             findplus.mcp.errors), or (text, status) for the export tool.
Constraints: Loopback only (enforced by the daemon); no retries; 30s/60s
             timeouts. Never raises for a reachable-but-unhappy daemon: an
             MCP client gets an error object, not a protocol-level failure.
"""

from __future__ import annotations

import httpx

from findplus.honesty import FIND_HUB
from findplus.mcp import errors

#: get_text's status for "could not reach the daemon at all".
UNREACHABLE = 0


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
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return errors.daemon_down()
        except httpx.TransportError as exc:
            return errors.error(
                "upstream", f"daemon request failed: {type(exc).__name__}", "check the daemon logs"
            )
        return self._parse(r)

    @staticmethod
    def _parse(r: httpx.Response) -> dict:
        mapped = errors.from_status(r.status_code, r.text)
        if mapped is not None:
            return mapped
        if not r.content:  # 204 No Content (DELETE) is a success with no body
            return {}
        try:
            return r.json()
        except ValueError:
            return errors.error(
                "upstream", "daemon returned a non-JSON response", "check the daemon logs"
            )

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
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return errors.daemon_down(), None
        except httpx.TransportError as exc:
            return errors.error(
                "upstream", f"daemon request failed: {type(exc).__name__}", "check the daemon logs"
            ), None
        cookie_val = r.cookies.get("findplus_session")
        parsed = self._parse(r)
        return parsed, (None if "error" in parsed else cookie_val)

    async def get_text(self, path: str, params: dict | None = None) -> tuple[str, int]:
        try:
            r = await self._send("GET", path, 60.0, params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return "", UNREACHABLE
        except httpx.TransportError as exc:
            return type(exc).__name__, 599
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

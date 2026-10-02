"""A stub desktop bridge and a fake in-app sign-in daemon for the 1.2 card tests.

Purpose    : Make the dashboard believe it runs inside the Find+ desktop app
             (window.__findplus_native + window.__TAURI__ with core.invoke and
             event.listen), record every command the page sends, and let a test
             emit the shell's events (signin-progress, signin-result,
             auth-attention, signin-apple-sheet). FakeNativeDaemon answers the
             native routes (begin, progress, cancel) and /api/auth/status with a
             phase the test moves along, for the paths the real daemon cannot
             reach without Google (a real token exchange). shell_event() posts
             to the REAL daemon with the shell's headers, for the paths it can.
Inputs     : A Playwright page; the live_server base URL.
Outputs    : install_bridge(), emit(), invokes(), FakeNativeDaemon, shell_event().
Constraints: No real window, browser, Finder or network: the bridge is plain
             JavaScript in the page and every daemon call stays on 127.0.0.1.
             Neutral names only (alex@example.invalid).
"""

from __future__ import annotations

import json

import httpx

ACCOUNT = "alex@example.invalid"
APPLE_ACCOUNT = "sam@example.invalid"

BRIDGE_JS = """
(() => {
  const opts = %s;
  const shell = { calls: [], listeners: {}, result: opts.result || "opened", fail: !!opts.fail };
  window.__fpShell = shell;
  window.__findplus_native = true;
  window.__FP_TEST_NATIVE_POLL_MS__ = opts.pollMs || 60;
  window.__FP_TEST_POLL_MS__ = opts.pollMs || 60;
  const core = {
    invoke: async (cmd, args) => {
      shell.calls.push({ cmd, args: JSON.parse(JSON.stringify(args || {})) });
      if (cmd === "open_signin_window") {
        if (shell.fail) throw new Error("boom");
        return args && args.provider === "apple" ? "apple_sheet" : shell.result;
      }
      if (cmd === "close_signin_window") return "closed";
      if (cmd === "request_notification_permission") return "granted";
      throw new Error("unknown command " + cmd);
    },
  };
  const event = {
    listen: async (name, cb) => {
      (shell.listeners[name] = shell.listeners[name] || []).push(cb);
      return () => {
        const list = shell.listeners[name] || [];
        const at = list.indexOf(cb);
        if (at >= 0) list.splice(at, 1);
      };
    },
  };
  window.__TAURI__ = opts.noEvents ? { core } : { core, event };
  window.__fpEmit = (name, payload) =>
    (shell.listeners[name] || []).slice().forEach((cb) => cb({ event: name, payload, id: 1 }));
})();
"""


async def install_bridge(page, **opts) -> None:
    """Before navigation: the page boots as the desktop app's main window."""
    await page.add_init_script(BRIDGE_JS % json.dumps(opts))


async def emit(page, name: str, payload) -> None:
    await page.evaluate("([n, p]) => window.__fpEmit(n, p)", [name, payload])


async def invokes(page, cmd: str = "open_signin_window") -> list[dict]:
    calls = await page.evaluate("() => window.__fpShell.calls")
    return [c["args"] for c in calls if c["cmd"] == cmd]


def progress(phase: str, **extra) -> dict:
    """A GET .../native/progress body (contract §3.6)."""
    body = {
        "phase": phase, "message": "", "mode": "signin", "account": None, "unlocked": False,
        "reason": None, "updated_at": "2026-10-02T09:00:00+00:00", "blocked_at": None,
        "start_with": "window", "fallback": None, "generation": 1,
    }
    body.update(extra)
    return body


def auth_status(*, google=False, apple=False, needs_g=(), att_g="none", att_a="none",
                native=None) -> dict:
    """A GET /api/auth/status body with the 1.2 fields."""
    return {
        "providers": [
            {"id": "google-find-hub", "signed_in": google, "account": ACCOUNT if google else None,
             "needs": list(needs_g), "attention": att_g, "deep_link": None},
            {"id": "apple-find-my", "signed_in": apple,
             "account": APPLE_ACCOUNT if apple else None, "needs": [], "attention": att_a,
             "deep_link": None},
        ],
        "google_helper_installed": False,
        "google_signin_generation": 1,
        "google_native": native or progress("idle"),
        "deep_links": {},
    }


class FakeNativeDaemon:
    """page.route answers for begin/progress/cancel/status, driven by the test."""

    def __init__(self, page) -> None:
        self.page = page
        self.phase = progress("idle")
        self.status = auth_status()
        self.begins: list[dict] = []
        self.cancels = 0
        self.begin_status = 200

    async def install(self) -> None:
        await self.page.route("**/api/auth/google/native/begin", self._begin)
        await self.page.route("**/api/auth/google/native/progress", self._progress)
        await self.page.route("**/api/auth/google/native/cancel", self._cancel)
        await self.page.route("**/api/auth/status", self._status)

    def set_phase(self, phase: str, **extra) -> None:
        self.phase = progress(phase, **extra)

    async def _begin(self, route) -> None:
        body = json.loads(route.request.post_data or "{}")
        self.begins.append({"body": body, "origin": route.request.headers.get("origin")})
        if self.begin_status != 200:
            await route.fulfill(status=self.begin_status, json={"detail": "Locked", "code": "x"})
            return
        self.set_phase("connecting", mode=body.get("mode", "signin"))
        await route.fulfill(json={"state": "fake-state", "mode": body.get("mode", "signin"),
                                  "window": {"timeout_seconds": 600}, "generation": 1})

    async def _progress(self, route) -> None:
        await route.fulfill(json=self.phase)

    async def _cancel(self, route) -> None:
        self.cancels += 1
        self.set_phase("cancelled", message="Cancelled. Nothing changed.")
        await route.fulfill(json={"phase": "cancelled", "message": "", "fallback": None})

    async def _status(self, route) -> None:
        await route.fulfill(json=self.status)


async def shell_event(base_url: str, state: str, event: str, reason: str | None = None) -> dict:
    """POST .../native/event to the real daemon exactly as the shell does."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/api/auth/google/native/event",
            json={"state": state, "event": event, "reason": reason},
            headers={"Origin": base_url, "X-FindPlus-Client": "signin-window"},
        )
    return response.json()


async def live_log(page, selector: str) -> None:
    """Record every text the live region gets, to prove each is announced once."""
    await page.evaluate(
        """(sel) => {
          const node = document.querySelector(sel);
          window.__fpLive = [];
          new MutationObserver(() => {
            const text = node.textContent.trim();
            if (text) window.__fpLive.push(text);
          }).observe(node, { childList: true, characterData: true, subtree: true });
        }""",
        selector,
    )

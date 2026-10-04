"""The page and the desktop shell agree on attention words, and the page says it is ready (O3).

Purpose    : The Rust shell's `auth-attention` payload uses signin / unlock / null;
             the daemon uses reauth / unlock / none. The page now reads both through
             one helper. It also calls the shell's `webview_ready` command once its
             listeners are in (an older shell without it, or a plain tab, must not
             break anything).
Constraints: A stub bridge only; no real window, browser or network beyond loopback.
"""

from __future__ import annotations

import pytest

from ._native_stub import FakeNativeDaemon, auth_status, install_bridge, invokes
from ._signin_helpers import wait_text
from .test_signin_lost_auth import ACTION, _health, _status_with

pytestmark = pytest.mark.asyncio(loop_scope="session")

ATTENTION = "/static/app/signin/attention.js"


async def _boot(page, base_url, holder, *, extra_init: str = "") -> FakeNativeDaemon:
    await install_bridge(page)
    if extra_init:
        await page.add_init_script(extra_init)
    fake = FakeNativeDaemon(page)
    await fake.install()
    await _status_with(page, holder)
    await page.goto(base_url + "/#dashboard")
    return fake


async def test_both_vocabularies_normalise_to_one(page, base_url):
    await page.goto(base_url + "/")
    result = await page.evaluate(
        """async (path) => {
          const m = await import(path);
          const words = ["signin", "reauth", "unlock", "none", null, undefined, "", "toString"];
          return {
            words: words.map((w) => m.normalizeAttention(w)),
            shell: m.normalizeAttentionPayload({ google: "signin", apple: null }),
            daemon: m.normalizeAttentionPayload({ google: "unlock", apple: "reauth" }),
            junk: m.normalizeAttentionPayload("nope"),
            notice: (m.attentionNotice([{ name: "google-find-hub", attention: "signin" }]) || {})
              .kind,
          };
        }""",
        ATTENTION,
    )
    assert result["words"] == ["reauth", "reauth", "unlock", "none", "none", "none", "none", "none"]
    assert result["shell"] == {"google": "reauth", "apple": "none"}
    assert result["daemon"] == {"google": "unlock", "apple": "reauth"}
    assert result["junk"] == {"google": "none", "apple": "none"}
    assert result["notice"] == "reauth"  # the shell's word still raises the banner


async def test_the_page_calls_webview_ready_once_its_listeners_are_in(page, base_url):
    holder = {"health": _health()}
    await _boot(page, base_url, holder)
    await page.wait_for_function(
        "() => window.__fpShell.calls.some((c) => c.cmd === 'webview_ready')", timeout=15000
    )
    state = await page.evaluate(
        """() => {
          const order = window.__fpShell.calls.map((c) => c.cmd);
          return {
            ready: order.filter((c) => c === 'webview_ready').length,
            apple: (window.__fpShell.listeners['signin-apple-sheet'] || []).length,
            attention: (window.__fpShell.listeners['auth-attention'] || []).length,
          };
        }"""
    )
    assert state == {"ready": 1, "apple": 1, "attention": 1}
    assert await invokes(page, "webview_ready") == [{}]


async def test_a_shell_without_webview_ready_changes_nothing(page, base_url):
    """An older app rejects the command; the banner and events still work."""
    holder = {"health": _health(google="reauth")}
    refuse = """
      window.__refused = [];
      const wrap = () => {
        const core = window.__TAURI__ && window.__TAURI__.core;
        if (!core || core.__wrapped) return;
        const real = core.invoke;
        core.invoke = async (cmd, args) => {
          if (cmd === 'webview_ready') {
            window.__refused.push(cmd);
            throw new Error('no such command');
          }
          return real(cmd, args);
        };
        core.__wrapped = true;
      };
      wrap();
    """
    fake = await _boot(page, base_url, holder, extra_init=refuse)
    fake.status = auth_status(att_g="reauth")
    await wait_text(page, "#alert", "Google signed Find+ out")
    assert await page.locator(ACTION).inner_text() == "Sign in again"
    assert await page.evaluate("() => window.__refused") == ["webview_ready"]


async def test_in_a_plain_tab_nothing_is_called(page, base_url):
    await page.goto(base_url + "/#dashboard")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']", timeout=15000)
    assert await page.evaluate("() => typeof window.__fpShell") == "undefined"

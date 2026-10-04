"""A stale "locked" banner clears the moment the account is unlocked (O17).

Purpose    : After a successful unlock the last poll run still says
             `needs_shared_key` until the NEXT poll is recorded. The banner used
             to keep saying "locked" in that gap. The daemon's own provider_health
             (signed in, attention "none") now wins over that history.
Constraints: /api/status is stubbed through StatusFeed; no provider contact.
"""

from __future__ import annotations

import pytest

from ._live_helpers import feed_for, open_dashboard, reload_status

pytestmark = pytest.mark.asyncio(loop_scope="session")

LOCKED = {t: ("needs_shared_key", 0) for t in ("TAG-HOME", "TAG-AWAY", "TAG-STALE")}
GOOGLE = "google-find-hub"


def _health(attention: str, authenticated: bool = True) -> list[dict]:
    return [
        {"name": GOOGLE, "available": True, "authenticated": authenticated, "attention": attention}
    ]


async def test_the_locked_banner_clears_when_the_key_is_unlocked_before_the_next_poll(
    page, base_url
):
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 400, provider_health=_health("none"))
    # Locked first: the daemon asks for the unlock, the banner says so.
    feed.body["provider_health"] = _health("unlock")
    await open_dashboard(page, base_url)
    text = page.locator("#alert .alert-text")
    await text.wait_for(state="visible")
    assert "ncrypted" in await text.inner_text() or "nlock" in await text.inner_text()

    # Unlocked now; the newest runs are still the old needs_shared_key ones.
    feed.body["provider_health"] = _health("none")
    await reload_status(page)
    await page.wait_for_function(
        "() => { const a = document.querySelector('#alert .alert-text');"
        " return !a || !/ncrypted|nlock/.test(a.textContent); }"
    )
    assert await page.locator("#alert .alert-action", has_text="Unlock locations").count() == 0
    # The timeline's empty pane does not claim "locked" either.
    kind = await page.evaluate(
        "() => import('/static/app/poll_cycle.js').then(async (m) =>"
        " m.emptyKind((await import('/static/app/state.js')).state.status))"
    )
    assert kind != "locked"


async def test_a_locked_run_stays_when_no_google_row_is_known(page, base_url):
    """Without provider_health the page knows nothing, so it keeps the old behaviour."""
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 410, provider_health=[])
    await open_dashboard(page, base_url)
    action = page.locator("#alert .alert-action")
    await action.wait_for(state="visible")
    assert (await action.inner_text()) == "Unlock locations"


async def test_a_signed_out_google_row_does_not_hide_the_locked_run(page, base_url):
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 420, provider_health=_health("none", authenticated=False))
    await open_dashboard(page, base_url)
    action = page.locator("#alert .alert-action")
    await action.wait_for(state="visible")
    assert (await action.inner_text()) == "Unlock locations"

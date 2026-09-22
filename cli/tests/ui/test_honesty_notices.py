"""The dashboard footer names the right provider (E1 honesty pass F1).

The footer rendered `honesty.FIND_HUB` unconditionally, so someone tracking only
Apple accessories read that their tags report through Google's Find Hub network.
Seed data (cli/tests/ui/conftest.py) includes the untracked Apple device TAG-AIR
so a loaded dashboard always has one provider of each kind.
"""

from __future__ import annotations

import pytest

from findplus import honesty

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")


async def test_footer_shows_the_apple_sentence_when_an_apple_tracker_is_present(page, base_url):
    """Both sentences render, each verbatim from /api/config.notices."""
    await _open_dashboard(page, base_url)

    await page.wait_for_function(
        "() => !document.getElementById('apple-notice').hidden",
        timeout=5000,
    )

    assert await page.locator("#apple-notice").text_content() == honesty.APPLE
    assert await page.locator("#findhub-notice").text_content() == honesty.FIND_HUB


async def test_footer_hides_the_apple_sentence_without_an_apple_tracker(page, base_url):
    """The notice is device-derived, not a constant: a Google-only list hides it."""
    await _open_dashboard(page, base_url)
    await page.wait_for_function(
        "() => !document.getElementById('apple-notice').hidden",
        timeout=5000,
    )

    hidden = await page.evaluate(
        """async () => {
            const [state, devices] = await Promise.all([
                import('/static/app/state.js'),
                import('/static/app/devices.js'),
            ]);
            state.state.devices = state.state.devices.filter(
                (d) => d.provider !== 'apple-find-my'
            );
            devices.syncProviderNotice();
            const el = document.getElementById('apple-notice');
            return el.hidden && el.textContent === '';
        }"""
    )
    assert hidden is True


async def test_footer_hides_the_findhub_sentence_for_an_apple_only_user(page, base_url):
    """The finding itself: an AirTag-only user must not be told about Find Hub.

    CR-C-E1 F5 -- the first fix gated only #apple-notice, so main.js still
    rendered honesty.FIND_HUB unconditionally and the false sentence stayed on
    screen for exactly the user the honesty pass was about.
    """
    await _open_dashboard(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('findhub-notice').textContent !== ''",
        timeout=5000,
    )

    state_after = await page.evaluate(
        """async () => {
            const [state, devices] = await Promise.all([
                import('/static/app/state.js'),
                import('/static/app/devices.js'),
            ]);
            state.state.devices = state.state.devices.map(
                (d) => ({ ...d, provider: 'apple-find-my' })
            );
            devices.syncProviderNotice();
            const fh = document.getElementById('findhub-notice');
            const ap = document.getElementById('apple-notice');
            return {
                findhub: { hidden: fh.hidden, text: fh.textContent },
                apple: { hidden: ap.hidden, text: ap.textContent },
            };
        }"""
    )
    assert state_after["findhub"] == {"hidden": True, "text": ""}
    assert state_after["apple"] == {"hidden": False, "text": honesty.APPLE}


async def test_the_footer_sentences_are_blanked_by_the_lock(page, base_url):
    """Both are device-derived, so both leak the tracked networks behind a lock."""
    await _open_dashboard(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('findhub-notice').textContent !== ''",
        timeout=5000,
    )

    blanked = await page.evaluate(
        """async () => {
            const lock = await import('/static/app/lock.js');
            await lock.purgeRenderedData();
            return ['findhub-notice', 'apple-notice'].every((id) => {
                const el = document.getElementById(id);
                return el.hidden && el.textContent === '';
            });
        }"""
    )
    assert blanked is True


async def _assert_chrome_names_apple_only_when_every_device_is_apple(page) -> None:
    """Set every device to apple-find-my, re-sync the chrome, and confirm no
    surface still reads "Google"/"Find Hub" -- half of
    test_the_chrome_around_the_footer_names_the_right_network's check."""
    apple_only = await page.evaluate(
        """async () => {
            const [state, devices] = await Promise.all([
                import('/static/app/state.js'),
                import('/static/app/devices.js'),
            ]);
            state.state.devices = state.state.devices.map(
                (d) => ({ ...d, provider: 'apple-find-my', is_tracked: true })
            );
            devices.syncProviderChrome();
            return {
                poll: document.getElementById('btn-poll').title,
                observed: document.getElementById('card-observed-label').textContent,
                heading: document.getElementById('device-modal-title').textContent,
                note: document.getElementById('device-modal-note').textContent,
            };
        }"""
    )
    for where, text in apple_only.items():
        assert "Google" not in text, f"{where} still says Google to an Apple-only user: {text}"
        assert "Find Hub" not in text, f"{where} still says Find Hub: {text}"
    assert apple_only["observed"] == "Last observed by Find My"
    assert apple_only["heading"] == "Devices on this Apple account"


async def test_the_chrome_around_the_footer_names_the_right_network(page, base_url):
    """honesty round 2 F3: round 1 gated the sentence and left the chrome Google-only.

    An Apple-only user still read "Last observed by Find Hub", "Queries Google
    once, now", "Devices on this Google account" and "about N Google requests
    per hour" — seven strings around the one sentence that had been fixed.
    """
    await _open_dashboard(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('findhub-notice').textContent !== ''",
        timeout=5000,
    )

    await _assert_chrome_names_apple_only_when_every_device_is_apple(page)

    google_only = await page.evaluate(
        """async () => {
            const [state, devices] = await Promise.all([
                import('/static/app/state.js'),
                import('/static/app/devices.js'),
            ]);
            state.state.devices = state.state.devices.map(
                (d) => ({ ...d, provider: 'google-find-hub', is_tracked: true })
            );
            devices.syncProviderChrome();
            return document.getElementById('card-observed-label').textContent;
        }"""
    )
    assert google_only == "Last observed by Find Hub"


async def test_the_markup_asserts_no_network_before_devices_load(page, base_url):
    """The pre-load default must not be a claim: a fresh page has no device list."""
    import re
    from pathlib import Path

    shell = Path(__file__).resolve().parents[3] / "web" / "index.html"
    text = shell.read_text()
    for partial in (shell.parent / "partials").glob("*.html"):
        text += partial.read_text()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    assert "Google" not in text
    assert "Find Hub" not in text

"""A provider-controlled device name cannot inject markup into the dashboard.

E1 security round 3 F1: a tag's `name` and an observation's `source` are set by
the provider, so anyone who can rename a tracker in the linked Google or Apple
account wrote into the watcher's dashboard. Five template sites interpolated
them into innerHTML unescaped. The CSP blocked script execution, but nothing
blocked an injected `<input type="checkbox" checked value="victim-device">`
landing inside #device-list -- which the Save button then POSTs to
/api/devices/track, so saving the dialog started polling a device the owner
never selected.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PAYLOAD = '<img src=x onerror=alert(1)><input type="checkbox" checked value="victim-device">'


async def test_the_escaper_neutralises_markup(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")

    out = await page.evaluate(
        """async (payload) => {
            const state = await import('/static/app/state.js');
            return {
                escaped: state.esc(payload),
                nullish: state.esc(null),
                number: state.esc(7),
            };
        }""",
        PAYLOAD,
    )
    assert "<img" not in out["escaped"]
    assert "<input" not in out["escaped"]
    assert out["escaped"].startswith("&lt;img")
    assert out["nullish"] == ""
    assert out["number"] == "7"


async def test_a_hostile_device_name_cannot_smuggle_a_checkbox(page, base_url):
    """The concrete consequence: an injected checked input is a tracked device."""
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")

    result = await page.evaluate(
        """async (payload) => {
            const [state, devices] = await Promise.all([
                import('/static/app/state.js'),
                import('/static/app/devices.js'),
            ]);
            state.state.devices = [
                { device_id: 'TAG-EVIL', name: payload, is_tracked: false,
                  observation_count: 0, provider: 'google-find-hub' },
            ];
            devices.renderDeviceModal();
            const host = document.getElementById('device-list');
            return {
                inputs: host.querySelectorAll('input').length,
                images: host.querySelectorAll('img').length,
                checked: [...host.querySelectorAll('input:checked')].map((i) => i.value),
                nameText: host.querySelector('.d-name').textContent,
            };
        }""",
        PAYLOAD,
    )

    assert result["images"] == 0, "the name injected an element"
    assert result["inputs"] == 1, "only the row's own checkbox may exist"
    assert result["checked"] == [], "an injected checked input would be POSTed as tracked"
    assert result["nameText"] == PAYLOAD, "the name must still render, as text"


async def test_a_hostile_name_cannot_break_out_of_the_timeline_block(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")

    result = await page.evaluate(
        """async (payload) => {
            const [state, timeline] = await Promise.all([
                import('/static/app/state.js'),
                import('/static/app/timeline.js'),
            ]);
            state.state.timeline = {
                tracks: [{
                    device_id: 'TAG-EVIL',
                    device_name: payload,
                    points: [],
                    stats: {
                        observation_count: 0,
                        approximate_distance_miles: 0,
                        distance_label: 'Approximate',
                        movement_count: 0,
                    },
                }],
            };
            timeline.renderTracks();
            const host = document.getElementById('tracks');
            const name = host.querySelector('.track-name');
            return {
                images: host.querySelectorAll('img').length,
                inputs: host.querySelectorAll('input').length,
                nameText: name ? name.textContent : null,
            };
        }""",
        PAYLOAD,
    )

    assert result["images"] == 0, "the device name injected an element"
    assert result["inputs"] == 0
    assert result["nameText"] == PAYLOAD, "the name must still render, as text"

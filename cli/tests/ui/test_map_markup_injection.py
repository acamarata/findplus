"""Tracker names, place names and suspect reasons reach Leaflet as literal text, never markup."""

# ruff: noqa: E501

from __future__ import annotations

import pytest

from ._trips_helpers import open_day

pytestmark = pytest.mark.asyncio(loop_scope="session")

IMG = "<img src=x onerror=alert(1)>"
FORM = "<form action=https://example.invalid><input name=pin></form>"

_PERSON = """async ({img, form}) => {
  const m = await import('/static/app/person_map.js');
  const {state} = await import('/static/app/state.js');
  const layer = L.layerGroup().addTo(state.map);
  const pt = (n, s) => ({lat: 40 + n / 100, lon: -74, observed_at_local: '2026-01-01T08:0' + n + ':00', suspect: s, suspect_reason: s ? form : null});
  const ctx = {
    tracks: [{device_id: 'D1', points: [pt(1, false), pt(2, false), pt(3, true)]}],
    trips: new Map([['D1', {stays: [{id: 's1', latitude: 40, longitude: -74, duration_minutes: 30, place_id: 1, label: img, start_local: '2026-01-01T08:00:00', end_local: '2026-01-01T08:30:00'}]}]]),
    leadId: 'D1', showSuspect: true, colorOf: () => '#d9480f', nameOf: () => img + form, onPickStay: () => {},
  };
  m.drawPerson(layer, ctx);
  layer.eachLayer((l) => l.openTooltip && l.openTooltip());
}"""

_TRIPS = """async ({img, form}) => {
  const m = await import('/static/app/trips_map.js');
  const {state} = await import('/static/app/state.js');
  state.layer.clearLayers();
  const stay = {id: 's1', kind: 'stay', latitude: 40, longitude: -74, duration_minutes: 30, place_id: 1, label: img, start_local: '2026-01-01T08:00:00', end_local: '2026-01-01T08:30:00', fix_count: 3};
  const trip = {id: 't1', kind: 'trip', points: [{latitude: 40, longitude: -74, local: '2026-01-01T08:31:00', at: '2026-01-01T08:31:00Z'}, {latitude: 40.02, longitude: -74, local: '2026-01-01T08:39:00', at: '2026-01-01T08:39:00Z'}], from: {place_id: 1, label: img}, to: {place_id: 2, label: form}, distance_meters: 100, start_local: '2026-01-01T08:30:00', end_local: '2026-01-01T08:40:00', duration_minutes: 10, fix_count: 0};
  const out = {latitude: 40.01, longitude: -74, local: '2026-01-01T08:20:00', suspect_reason: form};
  localStorage.setItem('findplus.showSuspect', '1');
  m.drawStory({payload: {stays: [stay], trips: [trip], outliers: [out]}, routes: new Map(), selectedId: null, fixes: [], onPick: () => {}, showInside: false});
  state.layer.eachLayer((l) => l.openTooltip && l.openTooltip());
}"""

_PROBE = """() => ({
  forms: document.querySelectorAll('.leaflet-tooltip form, .leaflet-tooltip input, .leaflet-tooltip img, .leaflet-popup form, .leaflet-popup img').length,
  text: [...document.querySelectorAll('.leaflet-tooltip')].map((e) => e.textContent).join('|'),
})"""


async def _check(page, script: str) -> None:
    dialogs: list[str] = []
    page.on("dialog", lambda d: dialogs.append(d.message))
    await page.evaluate(script, {"img": IMG, "form": FORM})
    probe = await page.evaluate(_PROBE)
    assert probe["forms"] == 0, probe
    assert "<img" in probe["text"] or "<form" in probe["text"], probe
    assert not dialogs


async def test_person_map_tooltips_are_literal_text(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    await _check(trips_page, _PERSON)


async def test_trips_map_tooltips_are_literal_text(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    await _check(trips_page, _TRIPS)

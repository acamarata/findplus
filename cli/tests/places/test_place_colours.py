"""A new place gets the first palette colour no other place uses (dashboard 1.3, U6)."""

from __future__ import annotations

from findplus.labels import DEVICE_PALETTE


def _add(client, name: str, **extra) -> str:
    body = {"name": name, "latitude": 41.1, "longitude": -80.6, "radius_meters": 100, **extra}
    resp = client.post("/api/places", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["color"]


def test_places_walk_through_the_palette(client):
    assert [_add(client, f"Spot {i}") for i in range(3)] == DEVICE_PALETTE[:3]


def test_an_explicit_colour_is_kept_and_a_taken_colour_is_skipped(client):
    assert _add(client, "A", color=DEVICE_PALETTE[0]) == DEVICE_PALETTE[0]
    assert _add(client, "B") == DEVICE_PALETTE[1]


def test_palette_cycles_after_twelve(client):
    for i in range(12):
        _add(client, f"Spot {i}")
    assert _add(client, "Spot 12") == DEVICE_PALETTE[0]

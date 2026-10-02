"""Place kinds guessed from a name, and the order that decides a tie."""

from __future__ import annotations

import pytest

from findplus.places.kinds import guess_place_kind, validate_place_kind


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Home", "home"),
        ("Our House", "home"),
        ("Grandma's", "family"),
        ("Grandma's House", "family"),
        ("Nana\u2019s flat", "family"),
        ("St Mary's School", "school"),
        ("Head Office", "work"),
        ("Corner Shop", "shop"),
        ("Park", "other"),
        ("", "other"),
    ],
)
def test_guess_from_the_name(name: str, kind: str) -> None:
    assert guess_place_kind(name) == kind


def test_a_bad_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="kind must be one of"):
        validate_place_kind("moon")


def test_a_guessed_kind_stays_flagged_until_the_owner_confirms_it(client) -> None:
    body = {"name": "Home", "latitude": 41.1, "longitude": -80.6, "radius_meters": 150}
    made = client.post("/api/places", json={**body, "notify": False}).json()
    assert (made["kind"], made["kind_guessed"]) == ("home", True)
    picked = client.post("/api/places", json={**body, "name": "Gym", "kind": "other",
                                              "notify": False}).json()  # fmt: skip
    assert picked["kind_guessed"] is False
    confirmed = client.put(f"/api/places/{made['id']}", json={"kind": "home"}).json()
    assert (confirmed["kind"], confirmed["kind_guessed"]) == ("home", False)
    listed = {p["name"]: p["kind_guessed"] for p in client.get("/api/places").json()}
    assert listed == {"Home": False, "Gym": False}

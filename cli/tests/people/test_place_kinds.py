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

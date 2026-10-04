"""places.kind_guessed survives a JSONL export and import (r122 O7)."""

from __future__ import annotations

import json

from sqlalchemy import delete, select

from findplus.db import models as m
from findplus.db.portable import export_lines
from findplus.db.portable_import import import_lines
from findplus.places.repo import create_place

HEADER = json.dumps({"t": "header", "format": "findplus-export", "version": 1})


def _place(session, name: str, guessed: bool, kind: str = "school") -> None:
    create_place(
        session, name=name, latitude_e7=410000000, longitude_e7=-806000000, radius_meters=100,
        kind=kind, kind_guessed=guessed,
    )  # fmt: skip


def test_a_guessed_kind_stays_guessed_and_a_confirmed_one_stays_confirmed(session) -> None:
    _place(session, "Maple School", True)
    _place(session, "Elm Home", False, "home")
    session.flush()
    lines = list(export_lines(session))
    places = [json.loads(x) for x in lines if json.loads(x)["t"] == "place"]
    assert {p["name"]: p["kind_guessed"] for p in places} == {
        "Maple School": True,
        "Elm Home": False,
    }
    session.execute(delete(m.Place))
    session.flush()
    import_lines(session, lines)
    session.flush()
    got = {p.name: (p.kind, p.kind_guessed) for p in session.scalars(select(m.Place))}
    assert got == {"Maple School": ("school", True), "Elm Home": ("home", False)}


def test_an_older_export_without_the_field_imports_as_confirmed(session) -> None:
    old = json.dumps(
        {
            "t": "place",
            "name": "Old",
            "kind": "school",
            "latitude_e7": 1,
            "longitude_e7": 2,
            "radius_meters": 100,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    import_lines(session, [HEADER, old])
    got = session.scalar(select(m.Place))
    assert (got.kind, got.kind_guessed) == ("school", False)

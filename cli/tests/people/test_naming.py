"""people/naming.py and people/suggestions.py on the owner's real tracker names (spec § 2)."""

from __future__ import annotations

import pytest

from findplus.db.models import Group
from findplus.ingest import upsert_device
from findplus.people import suggestions
from findplus.people.naming import read_name

OWNER_NAMES = [
    "Ali Keys", "Ali Pixel 8a", "Ali Pixel Watch", "Ali Wallet", "Jamie", "Drew", "Kai",
    "Whiskers", "Noor", "Pixel 11 Pro", "Shadow", "Robin", "Robin Bag", "Sam Bag", "Sam Bike",
    "Sam Shoes Red", "Sam Shoes White",
]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "owner", "role", "confidence"),
    [
        ("Sam Shoes Red", "sam", "shoes", "high"),
        ("Ali Pixel 8a", "ali", "phone", "high"),
        ("Ali Pixel Watch", "ali", "watch", "high"),
        ("Sam's bag", "sam", "bag", "high"),
        ("Bag (Sam)", "sam", "bag", "high"),
        ("Bag Sam", "sam", "bag", "high"),
        ("Sam 2", "sam", None, "medium"),
        ("Rose Bag", "rose", "bag", "low"),
        ("Red Keys", "red", "keys", "low"),
        ("Pixel 11 Pro", None, "phone", None),
        ("Zoë Watch", "zoe", "watch", "high"),
    ],
)
def test_read_name(name, owner, role, confidence):
    r = read_name("d", name)
    assert (r.owner_key, r.role, r.confidence) == (owner, role, confidence)


def test_ali_and_alia_stay_apart():
    assert read_name("a", "Ali Keys").owner_key != read_name("b", "Alia Keys").owner_key


def _seed(session, names):
    for i, name in enumerate(names):
        upsert_device(session, f"d{i:02d}", name, provider="test-fake")
    from findplus.state import track_devices

    track_devices(session, [f"d{i:02d}" for i in range(len(names))], exclusive=False)
    session.flush()


def _by_name(preview):
    return {s["name"]: s for s in preview["suggestions"]}


def test_owner_names_give_the_expected_suggestions(session):
    _seed(session, OWNER_NAMES)
    preview = suggestions.build(session)
    by = _by_name(preview)
    assert {n: len(s["members"]) for n, s in by.items()} == {
        "Ali": 4, "Jamie": 1, "Drew": 1, "Kai": 1, "Whiskers": 1, "Noor": 1, "Shadow": 1,
        "Robin": 2, "Sam": 4,
    }  # fmt: skip
    assert by["Sam"]["confidence"] == "high"
    assert sorted(m["role"] for m in by["Sam"]["members"]) == ["bag", "bike", "shoes", "shoes"]
    assert by["Sam"]["preview"].startswith('Person "Sam": ')
    for pet in ("Whiskers", "Shadow"):
        assert by[pet]["kind"] == "pet" and by[pet]["ask_kind"] is True
        assert by[pet]["question"] == f"Is {pet} a person or a pet?"
    for person in ("Jamie", "Drew", "Kai", "Noor"):
        assert by[person]["kind"] == "person" and by[person]["ask_kind"] is True
    assert by["Robin"]["ask_kind"] is False
    assert [u["name"] for u in preview["unassigned"]] == ["Pixel 11 Pro"]
    assert preview["unassigned"][0]["question"] == "Whose is this?"


def test_preview_writes_nothing(session):
    _seed(session, ["Sam Bag", "Sam Bike"])
    suggestions.build(session)
    assert session.query(Group).count() == 0


def test_rose_bag_is_flagged_low(session):
    _seed(session, ["Rose Bag"])
    s = suggestions.build(session)["suggestions"][0]
    assert s["confidence"] == "low" and s["flags"] == ["owner_is_colour"]
    assert s["warning"]


def test_same_named_set_becomes_turn_into_a_person(session):
    from findplus.groups.repo import create_group

    _seed(session, ["Sam Bag", "Sam Bike"])
    create_group(session, name="sam", member_ids=["d00"])
    s = suggestions.build(session)["suggestions"][0]
    assert s["action"] == "convert" and s["preview"].startswith("Turn group sam into a person")


def test_accept_then_a_new_tracker_is_suggested_for_the_same_person(session):
    _seed(session, ["Sam Bag", "Sam Bike"])
    s = suggestions.build(session)["suggestions"][0]
    out = suggestions.accept(session, [s], [])
    assert out["people"][0]["name"] == "Sam"
    assert suggestions.build(session)["suggestions"] == []
    upsert_device(session, "helmet", "Sam Helmet", provider="test-fake")
    from findplus.state import track_devices

    track_devices(session, ["helmet"], exclusive=False)
    again = suggestions.build(session)
    assert again["suggestions"][0]["action"] == "add"
    assert again["suggestions"][0]["preview"] == "New tracker Sam Helmet looks like Sam's. Add it?"
    assert again["new_device_ids"] == ["helmet"]


def test_a_tracker_already_in_a_person_is_never_moved(session):
    from findplus.people.repo import create_person

    _seed(session, ["Sam Bag", "Sam Bike"])
    create_person(session, name="Brother", member_ids=["d00"])
    s = suggestions.build(session)["suggestions"]
    assert [x["device_id"] for x in s[0]["members"]] == ["d01"]


def test_dismissed_suggestion_stays_dismissed(session):
    _seed(session, ["Sam Bag", "Sam Bike"])
    key = suggestions.build(session)["suggestions"][0]["key"]
    suggestions.accept(session, [], [key])
    preview = suggestions.build(session)
    assert preview["suggestions"] == [] and preview["dismissed_count"] == 1

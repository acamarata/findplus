"""people/naming.py and people/suggestions.py on the owner's real tracker names (spec § 2)."""

from __future__ import annotations

import pytest

from findplus.db.models import Group
from findplus.ingest import upsert_device
from findplus.people import suggestions
from findplus.people.naming import read_name

OWNER_NAMES = [
    "Ali Keys", "Ali Pixel 8a", "Ali Pixel Watch", "Ali Wallet", "Amirah", "Deen", "Hannah",
    "Meong", "Omar", "Pixel 11 Pro", "Shadow", "Sumayah", "Sumayah Bag", "Zaid Bag", "Zaid Bike",
    "Zaid Shoes Red", "Zaid Shoes White",
]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "owner", "role", "confidence"),
    [
        ("Zaid Shoes Red", "zaid", "shoes", "high"),
        ("Ali Pixel 8a", "ali", "phone", "high"),
        ("Ali Pixel Watch", "ali", "watch", "high"),
        ("Zaid's bag", "zaid", "bag", "high"),
        ("Bag (Zaid)", "zaid", "bag", "high"),
        ("Bag Zaid", "zaid", "bag", "high"),
        ("Zaid 2", "zaid", None, "medium"),
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
        "Ali": 4, "Amirah": 1, "Deen": 1, "Hannah": 1, "Meong": 1, "Omar": 1, "Shadow": 1,
        "Sumayah": 2, "Zaid": 4,
    }  # fmt: skip
    assert by["Zaid"]["confidence"] == "high"
    assert sorted(m["role"] for m in by["Zaid"]["members"]) == ["bag", "bike", "shoes", "shoes"]
    assert by["Zaid"]["preview"].startswith('Person "Zaid": ')
    for pet in ("Meong", "Shadow"):
        assert by[pet]["kind"] == "pet" and by[pet]["ask_kind"] is True
        assert by[pet]["question"] == f"Is {pet} a person or a pet?"
    for person in ("Amirah", "Deen", "Hannah", "Omar"):
        assert by[person]["kind"] == "person" and by[person]["ask_kind"] is True
    assert by["Sumayah"]["ask_kind"] is False
    assert [u["name"] for u in preview["unassigned"]] == ["Pixel 11 Pro"]
    assert preview["unassigned"][0]["question"] == "Whose is this?"


def test_preview_writes_nothing(session):
    _seed(session, ["Zaid Bag", "Zaid Bike"])
    suggestions.build(session)
    assert session.query(Group).count() == 0


def test_rose_bag_is_flagged_low(session):
    _seed(session, ["Rose Bag"])
    s = suggestions.build(session)["suggestions"][0]
    assert s["confidence"] == "low" and s["flags"] == ["owner_is_colour"]
    assert s["warning"]


def test_same_named_set_becomes_turn_into_a_person(session):
    from findplus.groups.repo import create_group

    _seed(session, ["Zaid Bag", "Zaid Bike"])
    create_group(session, name="zaid", member_ids=["d00"])
    s = suggestions.build(session)["suggestions"][0]
    assert s["action"] == "convert" and s["preview"].startswith("Turn group zaid into a person")


def test_accept_then_a_new_tracker_is_suggested_for_the_same_person(session):
    _seed(session, ["Zaid Bag", "Zaid Bike"])
    s = suggestions.build(session)["suggestions"][0]
    out = suggestions.accept(session, [s], [])
    assert out["people"][0]["name"] == "Zaid"
    assert suggestions.build(session)["suggestions"] == []
    upsert_device(session, "helmet", "Zaid Helmet", provider="test-fake")
    from findplus.state import track_devices

    track_devices(session, ["helmet"], exclusive=False)
    again = suggestions.build(session)
    assert again["suggestions"][0]["action"] == "add"
    assert (
        again["suggestions"][0]["preview"] == "New tracker Zaid Helmet looks like Zaid's. Add it?"
    )
    assert again["new_device_ids"] == ["helmet"]


def test_a_tracker_already_in_a_person_is_never_moved(session):
    from findplus.people.repo import create_person

    _seed(session, ["Zaid Bag", "Zaid Bike"])
    create_person(session, name="Brother", member_ids=["d00"])
    s = suggestions.build(session)["suggestions"]
    assert [x["device_id"] for x in s[0]["members"]] == ["d01"]


def test_dismissed_suggestion_stays_dismissed(session):
    _seed(session, ["Zaid Bag", "Zaid Bike"])
    key = suggestions.build(session)["suggestions"][0]["key"]
    suggestions.accept(session, [], [key])
    preview = suggestions.build(session)
    assert preview["suggestions"] == [] and preview["dismissed_count"] == 1

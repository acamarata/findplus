"""D-P2-4: a provider name refresh never overwrites a user's label, icon or colour.

Purpose : `ingest.upsert_device` is called on every poll and every refresh. Its
          update branch must touch `name` and `last_seen_at` and nothing else,
          or a tag the user named "Mom" would quietly revert to whatever the
          network calls it. The guarantee is one line of code; these tests are
          what keeps it true.
"""

from __future__ import annotations

from findplus import labels
from findplus.ingest import upsert_device


def test_upsert_device_create_branch_sets_a_palette_color(session) -> None:
    device = upsert_device(session, "dev1", "Tag1")
    assert device.color == labels.palette_color_for("dev1")
    assert device.icon == "letter"
    assert device.label is None


def test_upsert_device_update_branch_never_touches_label_icon_color(session) -> None:
    device = upsert_device(session, "dev1", "Tag1")
    device.label, device.icon, device.color = "Mom", "lucide:user-round", "#37c67a"
    session.commit()

    refreshed = upsert_device(session, "dev1", "Tag1 Renamed")

    assert refreshed.name == "Tag1 Renamed"
    assert refreshed.label == "Mom"
    assert refreshed.icon == "lucide:user-round"
    assert refreshed.color == "#37c67a"


def test_upsert_device_update_branch_preserves_a_cleared_label(session) -> None:
    """A user who cleared the label gets no label back, invented from the name."""
    device = upsert_device(session, "dev1", "Tag1")
    device.label = None
    session.commit()

    refreshed = upsert_device(session, "dev1", "Tag1 Renamed")

    assert refreshed.name == "Tag1 Renamed"
    assert refreshed.label is None

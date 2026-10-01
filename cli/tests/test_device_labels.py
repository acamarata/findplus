"""Two trackers with one name stay distinguishable (UAT #7, #19).

The id tail is added only for a visible clash, so a unique name never changes.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.device_labels import id_tails, unique_names
from findplus.ingest import ingest_observations, upsert_device
from findplus.state import track_devices
from tests.conftest import make_observation

TWINS = ("AAAA-1111", "BBBB-1111")


def _add_twins() -> None:
    with session_scope() as session:
        for device_id in TWINS:
            upsert_device(session, device_id, "Twin Tag")
        track_devices(session, ["TAG-001", *TWINS], exclusive=True)
        ingest_observations(
            session,
            [
                make_observation(device_id=d, device_name="Twin Tag", minutes=m, lat=41.2 + i / 100)
                for i, d in enumerate(TWINS)
                for m in (0, 20)
            ],
            fetched_at=datetime(2026, 9, 18, 13, 5, tzinfo=UTC),
        )


def test_tail_is_the_shortest_that_separates_the_clash() -> None:
    assert id_tails(["AAAA-1111", "BBBB-1111"]) == {"AAAA-1111": "A-1111", "BBBB-1111": "B-1111"}
    assert id_tails(["T-00", "T-01"]) == {"T-00": "T-00", "T-01": "T-01"}


def test_only_a_clash_gets_a_tail(client: TestClient) -> None:
    _add_twins()
    with session_scope() as session:
        names = unique_names(session)
    assert names["TAG-001"] == "Moto Tag 2"
    assert names["AAAA-1111"] == "Twin Tag (A-1111)"
    assert names["BBBB-1111"] == "Twin Tag (B-1111)"


def test_an_untracked_never_seen_twin_does_not_force_a_tail(client: TestClient) -> None:
    with session_scope() as session:
        upsert_device(session, "GHOST-0001", "Moto Tag 2")
        assert unique_names(session)["TAG-001"] == "Moto Tag 2"


def test_export_filenames_and_kml_names_differ(client: TestClient) -> None:
    _add_twins()
    heads = {}
    for device_id in TWINS:
        res = client.get(f"/api/export?fmt=kml&day=2026-09-18&timezone=UTC&device_id={device_id}")
        assert res.status_code == 200
        heads[device_id] = res.headers["content-disposition"]
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        root = ElementTree.fromstring(res.text)
        doc_name = root.find(".//k:Document/k:name", ns).text
        names = [n.text for n in root.findall(".//k:Placemark/k:name", ns)]
        tail = device_id[-6:]
        assert doc_name == f"Twin Tag ({tail}) 2026-09-18"
        assert any(n == f"Twin Tag ({tail}) (1)" for n in names)
        assert not any(device_id in n for n in names)
    assert heads[TWINS[0]] != heads[TWINS[1]]
    assert re.search(r"findplus-Twin-Tag-A-1111-2026-09-18\.kml", heads[TWINS[0]])


def test_empty_csv_says_it_is_empty(client: TestClient) -> None:
    res = client.get("/api/export?fmt=csv&day=2026-01-01&timezone=UTC")
    assert "# No observations were recorded" in res.text
    assert res.text.splitlines()[-1].startswith("observation_id")


def test_group_presence_names_the_right_twin(client: TestClient) -> None:
    _add_twins()
    made = client.post("/api/groups", json={"name": "Twins", "member_ids": list(TWINS)})
    assert made.status_code in (200, 201), made.text
    presence = client.get(f"/api/groups/{made.json()['id']}/presence?window=600").json()
    names = {m["name"] for m in presence["members"]}
    assert names == {"Twin Tag (A-1111)", "Twin Tag (B-1111)"}

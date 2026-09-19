"""/api/config.notices carries the six honesty.md sentences verbatim.

Purpose    : PROMPT.md §2 invariant 4 requires honesty text to be
             test-enforced. These sentences are normative; any paraphrase,
             even a single-character drift, is a regression.
Constraints: Copied character-for-character from specs/honesty.md — never
             retyped from memory.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app

EXPECTED = {
    "find_hub": (
        "This history consists of locations reported through Google's Find Hub network. "
        "Moto Tag uses nearby participating Android devices to report its location. "
        "Location updates can therefore be delayed, sparse, or unavailable, and this "
        "application should not be treated as real-time emergency or child-safety GPS tracking."
    ),
    "apple": (
        "Apple Find My locations come from nearby Apple devices and can be delayed, "
        "sparse or unavailable. Find+ can only query accessories whose keys you hold; "
        "genuine AirTags require extracting pairing keys, which most users cannot do."
    ),
    "alerts_latency": (
        "Alerts inherit the network's delay. An arrival or departure may be reported "
        "minutes to hours late."
    ),
    "presence_stale": (
        "A tag with no recent fix is stale, not at home and not left behind. "
        "Find+ reports it as unknown."
    ),
    "lock_not_encryption": (
        "The app lock stops casual browsing. It does not encrypt the database; "
        "anyone with access to this user account or the disk can read it. Use FileVault."
    ),
    "not_affiliated": (
        "Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks."
    ),
}


@pytest.fixture
def client(tmp_db):
    # tmp_db (conftest.py) isolates this from any PIN a prior test left set
    # in the shared /tmp/findplus-tests-state fallback — /api/config is
    # gated by SessionAuthMiddleware while locked, so a leaked lock state
    # would 401 every request here.
    return TestClient(create_app())


def test_config_notices_present(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    notices = resp.json()["notices"]
    for key, sentence in EXPECTED.items():
        assert notices[key] == sentence, f"notices.{key} mismatch"


def test_config_notices_no_extra_keys(client):
    resp = client.get("/api/config")
    notices = resp.json()["notices"]
    assert set(notices.keys()) == set(EXPECTED.keys())

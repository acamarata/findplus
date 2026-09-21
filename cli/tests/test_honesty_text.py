"""/api/config.notices carries every honesty.md sentence verbatim.

Purpose    : PROMPT.md §2 invariant 4 requires honesty text to be
             test-enforced. These sentences are normative; any paraphrase,
             even a single-character drift, is a regression.
Constraints: Copied character-for-character from specs/honesty.md — never
             retyped from memory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app

REPO_ROOT = Path(__file__).parent.parent.parent

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
    "whatsapp_relay": (
        "WhatsApp alerts are relayed through CallMeBot, a third-party free service. Your alert "
        "text transits CallMeBot's servers before reaching WhatsApp. Delivery is best-effort with "
        "no guarantee. Find+ is not affiliated with WhatsApp, Meta or CallMeBot."
    ),
    "whatsapp_setup": (
        "To connect WhatsApp: add +34 623 91 22 04 to your phone's contacts, then send it the "
        'message "I allow callmebot to send me messages" from your own WhatsApp. CallMeBot '
        "replies with an API key within about two minutes — paste it below."
    ),
    "alerts_locked": (
        "Notifications are held while Find+ is locked. Unlock to see what you missed."
    ),
    "native_generic": (
        'By default, macOS notifications show a generic "Find+ alert" instead of who or '
        "where, because notification banners can appear on a locked screen. Turn on "
        "notification details in Settings to show the person and place — anyone who can see "
        "the screen then sees the same thing."
    ),
    "not_affiliated": (
        "Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks."
    ),
    "chrome_required": (
        "Google Chrome was not found on this machine. Google sign-in drives Chrome directly "
        "and cannot run without it. Install it from https://www.google.com/chrome/ and try "
        "again."
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


def test_alerts_js_latency_fallback_matches_honesty_sentence():
    """web/app/alerts.js:injectLatencyFallback() hardcodes this sentence as a
    same-text initialisation fallback for a failed/slow /api/config (the
    server-sourced value from notices.js:loadNotices() always wins once it
    lands — see the comment in notices.js). A literal, not a fetch, so a
    drift here would show honesty text that disagrees with honesty.py and
    never get caught by test_config_notices_present above, which only
    exercises the server side.
    """
    text = (REPO_ROOT / "web" / "app" / "alerts.js").read_text(encoding="utf-8")
    assert EXPECTED["alerts_latency"] in text, (
        "alerts.js's hardcoded latency fallback no longer matches honesty.ALERTS_LATENCY"
    )


def test_the_docs_do_not_advertise_a_verdict_the_engine_never_produces() -> None:
    """honesty round 2 F10: README and FAQ advertised an "apart" verdict.

    groups/presence.py produces all_together | partial | unknown. "apart" was a
    fourth vocabulary that existed only in the docs, so a reader waited for a
    verdict the engine cannot emit.
    """
    import re
    from pathlib import Path

    from findplus.groups.presence import Verdict

    root = Path(__file__).resolve().parents[2]
    produced = set(Verdict.__args__) if hasattr(Verdict, "__args__") else set()
    assert produced == {"all_together", "partial", "unknown"}

    for doc in (root / "README.md", root / ".github" / "wiki" / "FAQ.md"):
        text = doc.read_text()
        for match in re.findall(r"\(together,[^)]*\)", text):
            assert "apart" not in match, f"{doc.name} still advertises 'apart': {match}"


def test_the_readme_does_not_point_at_a_page_that_404s() -> None:
    """honesty round 2 F8: README sent readers to /docs, which is 404 by design."""
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text()
    assert "8647/docs" not in readme
    assert "8647/redoc" not in readme
    assert "8647/api/openapi.json" in readme


def test_the_readme_credits_the_dependency_that_is_actually_pinned() -> None:
    """honesty round 2 F13: the licence section credited the wrong FindMy project.

    cli/pyproject.toml pins `findmy>=0.10,<0.11`; PyPI's findmy 0.10.2 is
    malmeloo/FindMy.py (author "Mike Almeloo"), not biemster/FindMy. Provenance
    is the one section a reader trusts to be exact.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text()
    pyproject = (root / "cli" / "pyproject.toml").read_text()

    assert 'apple = ["findmy>=0.10,<0.11"]' in pyproject
    assert "malmeloo/FindMy.py" in readme
    assert "biemster" not in readme


def test_expected_is_a_subset_of_the_notices_dict():
    """No absolute count here (R-P2-5 asserts the eleven at E13).

    What this pins is that EXPECTED never names a key honesty.py does not have,
    which is the drift a retyped list would otherwise hide.
    """
    from findplus import honesty

    assert set(EXPECTED) <= set(honesty.NOTICES)
    for key, sentence in EXPECTED.items():
        assert honesty.NOTICES[key] == sentence, f"{key} drifted from honesty.py"


# CR-C-E12 F1: distinctive substrings, one per honesty.NOTICES key. Each
# fragment sits inside a single wrapped line of README.md's Honesty
# blockquote (same grep-style approach as lint-prose.sh's HONESTY_SUBSTRINGS
# and EM_DASH_ALLOWED), so a future notice dropped from the README fails with
# the specific key rather than a generic diff.
README_FRAGMENTS = {
    "find_hub": "Moto Tag uses nearby participating Android devices",
    "apple": "genuine AirTags require extracting pairing keys",
    "alerts_latency": "Alerts inherit the network's delay",
    "presence_stale": "stale, not at home and not left behind",
    "lock_not_encryption": "The app lock stops casual browsing",
    "whatsapp_relay": "relayed through CallMeBot, a third-party free",
    "whatsapp_setup": "two minutes — paste it below",
    "alerts_locked": "Notifications are held while Find+ is locked",
    "native_generic": "place — anyone who can see",
    "not_affiliated": "not affiliated with Apple or Google",
    "chrome_required": "cannot run without it",
}


def test_readme_contains_every_honesty_notice():
    """PRI hard rule 4 / R-P2-5: README's Honesty section must carry all
    eleven honesty.NOTICES sentences, not just the six from P1.

    Iterates honesty.NOTICES itself (never a hardcoded key list) so a twelfth
    notice added to honesty.py without a matching README_FRAGMENTS entry
    fails here instead of silently passing.
    """
    from findplus import honesty

    assert set(README_FRAGMENTS) == set(honesty.NOTICES), (
        "README_FRAGMENTS has drifted from honesty.NOTICES's key set"
    )
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for key, fragment in README_FRAGMENTS.items():
        assert fragment in honesty.NOTICES[key], f"{key} fragment does not match honesty.py"
        assert fragment in readme, f"README.md Honesty section is missing the {key} notice"

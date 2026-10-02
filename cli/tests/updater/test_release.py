"""updater/release.py: version order, which releases count, and where requests may go."""

from __future__ import annotations

import pytest

from findplus.updater import release
from findplus.updater.release import UpdateError, is_newer, parse_release

from ._fake_github import LATEST


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("1.2.2", "1.2.1", True),
        ("1.10.0", "1.9.9", True),
        ("v2.0.0", "1.99.0", True),
        ("1.2.1", "1.2.1", False),
        ("1.2.0", "1.2.1", False),
        ("1.2.1", "1.2.1.dev0", True),
        ("1.2.1.dev0", "1.2.1", False),
        ("garbage", "1.2.1", False),
        (None, "1.2.1", False),
    ],
)
def test_versions_compare_as_numbers(candidate, current, newer) -> None:
    assert is_newer(candidate, current) is newer


def _body(**over):
    return {
        "tag_name": "v1.3.0",
        "html_url": "https://github.com/acamarata/findplus/releases/tag/v1.3.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "FindPlus-1.3.0-aarch64.dmg", "browser_download_url": "https://x/a.dmg"},
            {
                "name": "FindPlus-1.3.0-aarch64.dmg.sha256",
                "browser_download_url": "https://x/a.sha",
            },
            {"name": "findplus-1.3.0.whl", "browser_download_url": "https://x/w"},
        ],
        **over,
    }


def test_a_published_release_names_its_dmg_and_checksum() -> None:
    rel = parse_release(_body())
    assert rel is not None and rel.version == "1.3.0"
    assert rel.dmg_url == "https://x/a.dmg" and rel.sha_url == "https://x/a.sha"


@pytest.mark.parametrize(
    "over", [{"draft": True}, {"prerelease": True}, {"tag_name": "v1.3.0rc1"}, {"tag_name": "x"}]
)
def test_drafts_and_prereleases_are_ignored(over) -> None:
    assert parse_release(_body(**over)) is None


def test_a_plain_http_override_off_this_machine_is_refused(monkeypatch) -> None:
    monkeypatch.setenv(release.API_ENV, "http://example.invalid")
    with pytest.raises(UpdateError):
        release.api_base()
    monkeypatch.setenv(release.API_ENV, "http://127.0.0.1:1234/")
    assert release.api_base() == "http://127.0.0.1:1234"


def test_real_downloads_must_be_this_repositorys_release_assets(monkeypatch) -> None:
    monkeypatch.delenv(release.API_ENV, raising=False)
    ok = "https://github.com/acamarata/findplus/releases/download/v1.3.0/FindPlus-1.3.0-aarch64.dmg"
    assert release.download_allowed(ok)
    assert not release.download_allowed("https://github.com/someone/else/releases/download/x.dmg")
    assert not release.download_allowed("http://github.com/acamarata/findplus/releases/download/x")


def test_no_release_yet_is_none_and_errors_are_plain_words(github) -> None:
    assert release.fetch_latest() is None
    github.routes[LATEST] = (500, b"{}")
    with pytest.raises(UpdateError, match="GitHub answered 500"):
        release.fetch_latest()


def test_an_unreachable_github_is_an_update_error(monkeypatch) -> None:
    monkeypatch.setenv(release.API_ENV, "http://127.0.0.1:9")
    with pytest.raises(UpdateError, match="Could not reach GitHub"):
        release.fetch_latest()

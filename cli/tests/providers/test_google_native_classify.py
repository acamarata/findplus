"""The blocked-window classifier and the window's host allow-list (pure, no I/O)."""

from __future__ import annotations

import pytest

from findplus.providers.google_findhub import native_classify as nc


@pytest.mark.parametrize(
    "host",
    ["accounts.google.com", "accounts.google.de", "accounts.google.co.uk", "accounts.youtube.com"],
)
def test_google_sign_in_hosts_are_allowed(host) -> None:
    assert nc.is_allowed_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "localhost",
        "accounts.google.com.evil.com",
        "evilaccounts.google.com",
        "accounts.google.evil",
        "findplus-bridge.invalid",
    ],
)
def test_everything_else_is_not(host) -> None:
    assert not nc.is_allowed_host(host)


def test_ordinary_pages_are_not_blocked() -> None:
    assert nc.classify("accounts.google.com", "/EmbeddedSetup") == nc.Verdict(False, None)
    assert nc.classify("myaccount.google.com", "/", "couldnt_sign_in") == nc.Verdict(False, None)


def test_a_rejected_path_on_another_host_is_not_a_google_block() -> None:
    assert nc.classify("www.google.com", "/signin/rejected").reason is None


def test_clean_report_lowercases_and_refuses_extras() -> None:
    assert nc.clean_report("Accounts.Google.com", "/x", None) == (
        "accounts.google.com",
        "/x",
        "unknown",
    )
    for bad in [("a b", "/", "normal"), ("h", "/?q", "normal"), ("h", "/", "the title")]:
        with pytest.raises(nc.ReportError):
            nc.clean_report(*bad)

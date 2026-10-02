"""The blocked-window classifier and the window's host allow-list (pure, no I/O)."""

from __future__ import annotations

import pytest

from findplus.providers.google_findhub import native_classify as nc


#: The same table as desktop/src-tauri/src/signin_hosts_tests.rs (r12 #2).
ALLOWED = [
    "accounts.google.com",
    "accounts.google.de",
    "accounts.google.co.uk",
    "accounts.youtube.com",
    "myaccount.google.com",
    "google.com",
    "www.google.de",
    "google.de",
    "consent.google.de",
    "consent.google.com.br",
    "www.google.co.uk",
    "play.google.com",
    "apis.google.com",
    "evilaccounts.google.com",  # only Google can name a google.com subdomain
    "fonts.gstatic.com",
    "gstatic.com",
    "fonts.googleapis.com",
    "lh3.googleusercontent.com",
    "www.recaptcha.net",
    "xn--80ak6aa92e.google.com",
]
REFUSED = [
    "",
    "google",
    "127.0.0.1",
    "localhost",
    "accounts.google.com.evil.com",
    "accounts.google.evil",
    "accounts.google.co.evil",
    "google.com.evil.net",
    "google.co.uk.evil.de",
    "evilgoogle.com",
    "notgstatic.com",
    "recaptcha.net.evil.io",
    "youtube.com",
    "accounts.google.com.",
    "accounts..google.com",
    "-x.google.com",
    "xn--ggle-0nda.com",
    "findplus-bridge.invalid",
    "login.microsoftonline.com",
    "a" * 250 + ".google.com",
]


@pytest.mark.parametrize("host", ALLOWED)
def test_google_sign_in_hosts_are_allowed(host) -> None:
    assert nc.is_allowed_host(host)
    assert nc.classify(host, "/").blocked is False


@pytest.mark.parametrize("host", REFUSED)
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

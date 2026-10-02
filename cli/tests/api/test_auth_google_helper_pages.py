"""Wording on the helper's begin and success pages.

Purpose    : the begin page says the helper needs Google Chrome, and the success
             page says "Unlocked" after an unlock but "Signed in" after a sign-in.
"""

from __future__ import annotations


def test_the_begin_page_says_the_helper_is_chrome_only(auth_client) -> None:
    body = auth_client.get("/auth/google/begin?state=abc").text
    assert "works in Google Chrome only" in body


def test_the_success_page_wording_follows_the_flow(auth_client) -> None:
    assert "<h1>Signed in</h1>" in auth_client.get("/auth/google/success").text
    assert "<h1>Unlocked</h1>" in auth_client.get("/auth/google/success?kind=unlock").text
    assert "<h1>Signed in</h1>" in auth_client.get("/auth/google/success?kind=junk").text

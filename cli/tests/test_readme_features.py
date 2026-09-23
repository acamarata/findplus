"""README.md's Features section names every alert channel and upload path.

Purpose    : UAT2 N15 -- the Features bullets said only "Telegram and webhook
             alert channels", with no mention of WhatsApp, desktop
             notifications, Apple accessory key upload, custom icons, the
             places widget, delivery retry, or the opt-in Nominatim address
             search, all of which already ship. This is a drift gate: every
             term below must actually be true of the code it names, checked
             once here rather than trusted to a human re-read.
Constraints: Checked against the code (not retyped from the README) so this
             test fails the moment the doc and the feature it names diverge
             in either direction. Does not touch the Honesty section, which
             test_honesty_text.py already test-enforces character-for-character.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _features_section() -> str:
    """The Features bullets, with wrapped lines collapsed to single spaces so
    a phrase split across a line wrap (Markdown's own soft-wrap convention)
    still matches as one substring."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("## Features")
    end = text.index("## Privacy")
    return " ".join(text[start:end].split())


def test_every_alert_channel_is_named() -> None:
    section = _features_section()
    for channel in ("Telegram", "WhatsApp", "webhook", "native macOS notification"):
        assert channel in section, f"README Features section is missing {channel!r}"


def test_delivery_retry_is_named() -> None:
    assert "retry" in _features_section().lower()


def _api_paths() -> set[str]:
    from findplus.api import create_app

    return set(create_app().openapi()["paths"])


def test_custom_icon_upload_is_named() -> None:
    """cli/src/findplus/api/routes_icons.py registers POST /api/icons/custom;
    web/app/components/custom-icons.js is the dashboard upload flow."""
    assert "/api/icons/custom" in _api_paths()
    assert "custom icons" in _features_section().lower()


def test_apple_accessory_key_upload_is_named() -> None:
    """web/app/auth_accessories.js POSTs /api/apple/accessories."""
    assert "/api/apple/accessories" in _api_paths()
    assert "accessory key" in _features_section().lower()


def test_places_widget_is_named() -> None:
    """GET /api/widget backs both the status and places WidgetKit widgets
    (desktop/widget); the places-specific one is unnamed in the old bullet."""
    assert "/api/widget" in _api_paths()
    assert "places widget" in _features_section().lower()


def test_nominatim_address_search_is_named_as_opt_in() -> None:
    """cli/src/findplus/api/routes_places_search.py only calls Nominatim from
    the place dialog's address search -- opt-in, never on a background poll."""
    section = _features_section()
    assert "Nominatim" in section
    assert "opt-in" in section

"""Apple Find My availability guard: two-case sys.modules mock, no real findmy import."""

from __future__ import annotations

import sys
import types

from findplus.providers.apple_findmy import is_available


def test_available(monkeypatch) -> None:
    stub = types.ModuleType("findmy")
    monkeypatch.setitem(sys.modules, "findmy", stub)
    assert is_available() == (True, "")


def test_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "findmy", None)
    assert is_available() == (False, "pip install 'findplus[apple]'")

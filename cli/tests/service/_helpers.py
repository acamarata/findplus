"""Shared helpers for the findplus.service command tests.

Purpose    : One definition of the detect_manager patch, which has to be applied
             in three places (runtime.py and watchdog.py import the name by
             reference at import time, so patching the facade alone does not
             control their dispatch).
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

import pytest


def patch_manager(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr("findplus.service.detect_manager", lambda: name)
    monkeypatch.setattr("findplus.service.runtime.detect_manager", lambda: name)
    monkeypatch.setattr("findplus.service.watchdog.detect_manager", lambda: name)

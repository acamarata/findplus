"""A frozen daemon inside Find+.app reports the app's version, not stale metadata.

1.2.0 and 1.2.1 shipped a sidecar whose dist-info said 1.1.5, so the 1.2.1 updater
saw its own release as newer. These tests pin the bundle-version source.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from findplus._bundle_version import bundle_version, enclosing_app
from findplus.updater.release import is_newer


def _app(tmp_path: Path, version: str | None) -> Path:
    contents = tmp_path / "Find+.app" / "Contents"
    sidecar = contents / "Resources" / "resources" / "findplus-daemon"
    sidecar.mkdir(parents=True)
    exe = sidecar / "findplus-daemon"
    exe.write_bytes(b"")
    info = {"CFBundleIdentifier": "com.acamarata.findplus"}
    if version:
        info["CFBundleShortVersionString"] = version
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump(info, fh)
    return exe


def test_frozen_sidecar_reports_the_app_bundle_version(tmp_path):
    exe = _app(tmp_path, "1.2.2")
    assert bundle_version(str(exe), frozen=True) == "1.2.2"
    assert enclosing_app(exe.resolve()) == (tmp_path / "Find+.app").resolve()


def test_bundle_version_stops_the_self_update_loop(tmp_path):
    exe = _app(tmp_path, "1.2.1")
    current = bundle_version(str(exe), frozen=True) or "1.1.5"
    assert not is_newer("1.2.1", current)
    assert is_newer("1.2.2", current)


def test_not_frozen_or_not_in_an_app_falls_back(tmp_path):
    exe = _app(tmp_path, "1.2.2")
    assert bundle_version(str(exe), frozen=False) is None
    loose = tmp_path / "findplus-daemon"
    loose.write_bytes(b"")
    assert bundle_version(str(loose), frozen=True) is None


def test_missing_or_broken_plist_falls_back(tmp_path):
    exe = _app(tmp_path, None)
    assert bundle_version(str(exe), frozen=True) is None
    (tmp_path / "Find+.app" / "Contents" / "Info.plist").write_bytes(b"not a plist")
    assert bundle_version(str(exe), frozen=True) is None

"""updater/devsource.py: a developer's local builds win unless a release is higher."""

from __future__ import annotations

import hashlib
import os
import plistlib
import time
from pathlib import Path

import pytest

from findplus.updater import devsource, store
from findplus.updater.apply import prepare
from findplus.updater.check import check, choose, scan_dev
from findplus.updater.status import result_path, status, tidy

OLD = time.time() - 3600


def make_app(folder: Path, version: str, payload: str = "build-1") -> Path:
    app = folder / "Find+.app"
    (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump({"CFBundleShortVersionString": version}, fh)
    (app / "Contents" / "MacOS" / "findplus").write_text(payload)
    for p in [app / "Contents" / "Info.plist", app / "Contents" / "MacOS" / "findplus"]:
        os.utime(p, (OLD, OLD))
    return app


def make_dmg(folder: Path, version: str, data: bytes = b"dmg") -> Path:
    dmg = folder / f"FindPlus-{version}-aarch64.dmg"
    dmg.write_bytes(data)
    sha = dmg.with_name(dmg.name + ".sha256")
    sha.write_text(hashlib.sha256(data).hexdigest() + "  " + dmg.name)
    for p in (dmg, sha):
        os.utime(p, (OLD, OLD))
    return dmg


@pytest.fixture
def dev(tmp_path: Path) -> Path:
    folder = tmp_path / "dev"
    folder.mkdir()
    return folder


def test_an_app_or_a_checked_dmg_is_found_and_a_fresh_one_waits(dev) -> None:
    make_app(dev, "1.2.1")
    assert devsource.find_build(dev)["kind"] == "app"
    make_dmg(dev, "1.2.2")
    assert devsource.find_build(dev)["version"] == "1.2.2"
    assert devsource.find_build(dev, now=OLD + 10) is None  # still being written
    assert devsource.find_build(dev / "missing") is None


def test_a_rebuild_of_the_same_version_has_a_new_fingerprint(dev) -> None:
    first = devsource.fingerprint_app(make_app(dev, "1.2.1", "build-1"))
    second = devsource.fingerprint_app(make_app(dev, "1.2.1", "build-two"))
    assert first != second


@pytest.mark.parametrize(
    ("dev_version", "release", "winner"),
    [("1.2.2", "1.2.1", "dev"), ("1.2.2", "1.3.0", "release"), ("1.3.0", "1.3.0", "dev"),
     ("1.2.1", None, "dev"), ("1.2.0", None, "none"), (None, "1.3.0", "release")],
)  # fmt: skip
def test_choose(dev_version, release, winner) -> None:
    build = {"source": "dev", "version": dev_version, "fingerprint": "f"} if dev_version else None
    assert choose(build, release, "1.2.1", stamp=None) == winner


def test_the_installed_build_is_not_installed_again(dev, installed, state_dir, in_app) -> None:
    make_app(dev, "1.2.1")
    scan_dev(state_dir, dev)
    assert status(state_dir, auto=True)["auto_install_ready"] is True
    from findplus.config import get_settings

    s = get_settings()
    out = prepare(state_dir, s.database_path, s.effective_backup_dir)
    assert out["kind"] == "app" and out["path"].endswith("Find+.app")
    result_path(state_dir).write_text("ok 1.2.1\n")
    tidy(state_dir)  # the new app's daemon starts
    assert status(state_dir, auto=True)["staged_version"] is None
    scan_dev(state_dir, dev)
    assert status(state_dir, auto=True)["staged_version"] is None
    make_app(dev, "1.2.1", "build-two")  # the developer rebuilds
    scan_dev(state_dir, dev)
    assert status(state_dir, auto=True)["staged_source"] == "dev"


def test_a_higher_release_beats_the_dev_build(dev, github, installed, state_dir, in_app) -> None:
    make_app(dev, "1.2.2")
    github.publish("1.3.0", b"release dmg")
    state = check(state_dir, download=True, dev_dir=dev)
    assert state["staged"]["source"] == "release" and state["staged"]["version"] == "1.3.0"


def test_a_dev_build_beats_a_lower_release_without_a_download(dev, github, installed, state_dir):
    make_app(dev, "1.3.1")
    github.publish("1.3.0", b"release dmg")
    state = check(state_dir, download=True, dev_dir=dev)
    assert state["staged"]["source"] == "dev"
    assert [h for h in github.hits if "/dl/" in h] == []
    assert list(store.updates_dir(state_dir).glob("*.dmg")) == []


def test_a_build_changed_after_staging_is_refused(dev, installed, state_dir) -> None:
    from findplus.config import get_settings
    from findplus.updater.release import UpdateError

    app = make_app(dev, "1.2.2")
    scan_dev(state_dir, dev)
    (app / "Contents" / "MacOS" / "findplus").write_text("half written")
    s = get_settings()
    with pytest.raises(UpdateError, match="changed after Find\\+ found it"):
        prepare(state_dir, s.database_path, s.effective_backup_dir)


def test_the_env_var_wins_over_the_setting(dev, session, monkeypatch) -> None:
    devsource.set_dev_dir(session, "/somewhere/else")
    assert devsource.dev_dir(session) == Path("/somewhere/else")
    monkeypatch.setenv(devsource.ENV, str(dev))
    assert devsource.dev_dir(session) == dev
    with pytest.raises(ValueError):
        devsource.set_dev_dir(session, "not/absolute")

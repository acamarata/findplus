"""packaging/scripts/update-app.sh: refuses bad apps before touching anything (r1 review #18).

Purpose    : Runs the real script against a fake app directory with stub `codesign`,
             `lipo`, `sysctl`, `launchctl`, `xattr` and friends on PATH. Checks the
             unsigned refusal and --force, the arm64 refusal, the leftover `.new`,
             the rollback when the swap fails, quarantine handling, the exact
             launchctl label match, and (automatic updates) the Team ID refusal,
             --verify-only, --result and starting the old app again after a failure.
Constraints: macOS only (PlistBuddy). Never touches /Applications or a real launchd.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "packaging" / "scripts" / "update-app.sh"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/libexec/PlistBuddy").exists(),
    reason="needs macOS PlistBuddy",
)

STUBS = {
    # `codesign -dv APP` prints the signing team: STUB_OLD_TEAM for the installed
    # app (under APP_DIR), STUB_NEW_TEAM for the new one. `--verify` obeys STUB_SIGNED.
    "codesign": 'if [ "$1" = -dv ]; then for a; do last="$a"; done; '
    'case "$last" in "$APP_DIR"/*) t="${STUB_OLD_TEAM:-}";; *) t="${STUB_NEW_TEAM:-}";; esac; '
    '[ -n "$t" ] && echo "TeamIdentifier=$t" >&2; exit 0; fi; '
    '[ "${STUB_SIGNED:-1}" = 1 ]',
    "lipo": 'echo "${STUB_ARCHS:-arm64}"',
    "sysctl": "echo 1",
    "pgrep": "exit 1",
    "osascript": "exit 0",
    "open": 'echo "$@" >> "$STUB_LOG/open"',
    "launchctl": 'echo "$@" >> "$STUB_LOG/launchctl"; '
    '[ "$1" = print ] && [ "$2" = "gui/$(id -u)/com.acamarata.findplus" ] || '
    '[ "$1" = kickstart ]',
    "xattr": 'echo "$@" >> "$STUB_LOG/xattr"',
    "mv": 'if [ "${STUB_MV_FAIL:-0}" = 1 ] && [ "${1##*.}" = new ]; then exit 1; fi; '
    'exec /bin/mv "$@"',
}


def _make_app(path: Path, version: str) -> Path:
    (path / "Contents" / "MacOS").mkdir(parents=True)
    with (path / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump({"CFBundleShortVersionString": version, "CFBundleExecutable": "findplus"}, fh)
    (path / "Contents" / "MacOS" / "findplus").write_text(version)
    return path


@pytest.fixture
def env(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/bash\n{body}\n")
        stub.chmod(0o755)
    log = tmp_path / "log"
    log.mkdir()
    apps = tmp_path / "apps"
    apps.mkdir()
    _make_app(apps / "Find+.app", "1.0.0")
    new = _make_app(tmp_path / "new" / "Find+.app", "2.0.0")
    environ = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "APP_DIR": str(apps),
        "STUB_LOG": str(log),
    }
    return environ, apps, new, log


def _run(environ, new: Path, *extra: str, **overrides: str):
    return subprocess.run(
        ["bash", str(SCRIPT), "--app", str(new), "--no-launch", *extra],
        env={**environ, **overrides},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _version(apps: Path) -> str:
    return (apps / "Find+.app" / "Contents" / "MacOS" / "findplus").read_text()


def test_an_unsigned_app_is_refused_and_nothing_changes(env) -> None:
    environ, apps, new, _log = env
    res = _run(environ, new, STUB_SIGNED="0")
    assert res.returncode == 1
    assert "signature" in res.stderr
    assert _version(apps) == "1.0.0"


def test_force_installs_an_unsigned_app_but_keeps_quarantine(env) -> None:
    environ, apps, new, log = env
    res = _run(environ, new, "--force", STUB_SIGNED="0")
    assert res.returncode == 0, res.stderr
    assert _version(apps) == "2.0.0"
    assert not (log / "xattr").exists()


def test_a_signed_app_installs_and_loses_quarantine(env) -> None:
    environ, apps, new, log = env
    res = _run(environ, new)
    assert res.returncode == 0, res.stderr
    assert _version(apps) == "2.0.0"
    assert "com.apple.quarantine" in (log / "xattr").read_text()
    assert not (apps / "Find+.app.old").exists()


def test_an_app_without_an_arm64_slice_is_refused(env) -> None:
    environ, apps, new, _log = env
    res = _run(environ, new, STUB_ARCHS="x86_64")
    assert res.returncode == 1
    assert "arm64" in res.stderr
    assert _version(apps) == "1.0.0"


def test_a_leftover_new_directory_is_not_merged_into(env) -> None:
    environ, apps, new, _log = env
    stale = apps / "Find+.app.new" / "Contents"
    stale.mkdir(parents=True)
    (stale / "stale.txt").write_text("old")
    res = _run(environ, new)
    assert res.returncode == 0, res.stderr
    assert not (apps / "Find+.app" / "Contents" / "stale.txt").exists()


def test_a_failed_swap_puts_the_old_app_back(env) -> None:
    environ, apps, new, _log = env
    res = _run(environ, new, STUB_MV_FAIL="1")
    assert res.returncode == 1
    assert _version(apps) == "1.0.0"
    assert not (apps / "Find+.app.old").exists()


def test_launchctl_is_asked_about_the_exact_label(env) -> None:
    environ, _apps, new, log = env
    assert _run(environ, new).returncode == 0
    calls = (log / "launchctl").read_text().splitlines()
    uid = str(os.getuid())
    assert f"print gui/{uid}/com.acamarata.findplus" in calls
    assert f"kickstart -k gui/{uid}/com.acamarata.findplus" in calls


def test_a_new_app_from_another_team_is_refused(env) -> None:
    environ, apps, new, _log = env
    res = _run(environ, new, STUB_OLD_TEAM="AAAA111111", STUB_NEW_TEAM="BBBB222222")
    assert res.returncode == 1
    assert "BBBB222222" in res.stderr and "AAAA111111" in res.stderr
    assert _version(apps) == "1.0.0"


def test_an_unsigned_new_app_cannot_replace_a_team_signed_one(env) -> None:
    environ, apps, new, _log = env
    res = _run(environ, new, STUB_OLD_TEAM="AAAA111111")
    assert res.returncode == 1
    assert "team none" in res.stderr
    assert _version(apps) == "1.0.0"


def test_the_same_team_installs(env) -> None:
    environ, apps, new, _log = env
    res = _run(environ, new, STUB_OLD_TEAM="AAAA111111", STUB_NEW_TEAM="AAAA111111")
    assert res.returncode == 0, res.stderr
    assert _version(apps) == "2.0.0"


def test_verify_only_checks_and_changes_nothing(env, tmp_path: Path) -> None:
    environ, apps, new, _log = env
    result = tmp_path / "result"
    res = _run(environ, new, "--verify-only", "--result", str(result))
    assert res.returncode == 0, res.stderr
    assert _version(apps) == "1.0.0"
    assert not result.exists()


def test_result_file_says_ok_with_the_version(env, tmp_path: Path) -> None:
    environ, _apps, new, _log = env
    result = tmp_path / "result"
    assert _run(environ, new, "--result", str(result)).returncode == 0
    assert result.read_text().strip() == "ok 2.0.0"


def test_a_failure_after_the_app_quit_starts_the_old_app_again(env, tmp_path: Path) -> None:
    """--wait-pid means the app already quit itself: a refusal must not leave it closed."""
    environ, apps, new, log = env
    result = tmp_path / "result"
    res = subprocess.run(
        ["bash", str(SCRIPT), "--app", str(new), "--wait-pid", "999999", "--result", str(result)],
        env={**environ, "STUB_MV_FAIL": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 1
    assert _version(apps) == "1.0.0"
    assert result.read_text().startswith("failed could not put the new app in place")
    assert str(apps / "Find+.app") in (log / "open").read_text()


def test_a_refusal_before_quitting_never_starts_anything(env, tmp_path: Path) -> None:
    environ, _apps, new, log = env
    result = tmp_path / "result"
    res = _run(environ, new, "--result", str(result), STUB_SIGNED="0")
    assert res.returncode == 1
    assert result.read_text().startswith("failed the new app's code signature")
    assert not (log / "open").exists()

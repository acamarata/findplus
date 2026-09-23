"""`findplus doctor [--repair] [--json]`: self-service installation diagnostics.

Purpose    : Eleven independent checks (python, state-dir/file permissions, DB
             schema head, provider auth, service units, port health, Chrome,
             alerts.json validity, legacy pre-rename database, optional desktop
             app) with permission and migration repair via --repair.
Inputs     : Settings (state dir, port); nothing here mutates unless --repair.
Outputs    : A DoctorCheck per check, printed as text or --json; exit 1 if any
             check still fails after an optional repair pass.
Constraints: Every check function is pure (no side effects). The service-units
             check goes through the pinned facade (service.is_installed() /
             service.plan()) — never a manager object, never direct subprocess.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import click
import httpx

from findplus.config import get_settings

from .doctor_perms import (
    DoctorCheck,
    check_sensitive_file_perms,
    check_state_dir_perms,
    repair_sensitive_file_perms,
    repair_state_dir_perms,
)

__all__ = [
    "DoctorCheck",
    "check_sensitive_file_perms",
    "check_state_dir_perms",
    "doctor_cmd",
    "repair_sensitive_file_perms",
    "repair_state_dir_perms",
]


def check_python() -> DoctorCheck:
    ok = sys.version_info >= (3, 12)
    return DoctorCheck("python_version", "Python >= 3.12", ok, f"Python {sys.version}")


def check_db_head() -> DoctorCheck:
    from findplus.db.migrate import current_revision, head_revision

    try:
        current = current_revision()
        head = head_revision()
    except Exception as exc:
        return DoctorCheck("db_head", "Database schema", False, str(exc)[:80], repairable=True)
    return DoctorCheck(
        "db_head",
        "Database schema",
        current == head,
        f"schema {current} (head {head})",
        repairable=True,
    )


def check_providers() -> DoctorCheck:
    """One line per registered provider: not configured / not signed-in / signed-in.

    Goes through the `findplus.providers` registry instead of grepping
    secrets.json for a Google-specific `token`/`session` key (that check was
    blind to Apple Find My, which stores nothing under either name — CF23,
    E9 review carry-forward #23). Never raises: a provider whose is_available()
    or is_authenticated() throws is reported as an error line, not a 500.
    """
    from findplus import honesty
    from findplus.providers.base import available_providers, get_provider

    names = available_providers()
    if not names:
        return DoctorCheck("providers", "Provider authentication", False, "no providers registered")

    lines: list[str] = []
    any_signed_in = False
    for name in names:
        try:
            p = get_provider(name)
            avail, reason = p.is_available()
            if not avail:
                status = f"not configured ({reason})"
            else:
                signed_in = p.is_authenticated()
                any_signed_in = any_signed_in or signed_in
                if not signed_in:
                    status = "not signed-in"
                else:
                    account = p.describe_auth().get("account")
                    status = f"signed-in ({account})" if account else "signed-in"
        except Exception as exc:
            status = f"error ({exc})"
        line = f"{name}: {status}"
        if name == "apple-find-my":
            line = f"{line} — {honesty.APPLE}"
        lines.append(line)

    return DoctorCheck("providers", "Provider authentication", any_signed_in, "; ".join(lines))


def check_units() -> DoctorCheck:
    from findplus import service

    installed = service.is_installed()
    if installed:
        p = service.plan()
        detail = f"unit at {p.unit_path}"
    else:
        detail = "service not installed"
    return DoctorCheck("service_units", "Service units", installed, detail)


def check_port(state_dir: Path, port: int) -> DoctorCheck:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2.0)
        passed = r.status_code in (200, 401)
        detail = f"HTTP {r.status_code}"
    except Exception:
        passed = False
        detail = "connection refused"
    return DoctorCheck("port", "Daemon port", passed, detail, repairable=False)


def check_chrome() -> DoctorCheck:
    """Whether the Google sign-in flow will find a Chrome to launch.

    UAT2 N1: a machine with Chrome installed still read "not found" because
    this only checked `google-chrome`/`google-chrome-stable` on PATH plus the
    system `/Applications` bundle. The candidate list mirrors
    `cli/vendor/GoogleFindMyTools/chrome_driver.py:find_chrome()`'s search
    (PRI rule 8: that file is never edited, so the check is kept in step with
    it here instead), so "found" here means the vendored flow will find it.

    Windows CI (E-windows-ci): the old else-branch fell through to the POSIX
    paths on win32 too, so this always said "not found" there. The win32
    branch checks `chrome`/`chrome.exe` on PATH plus find_chrome()'s three
    install roots, resolved from the real env vars (PROGRAMFILES,
    PROGRAMFILES(X86), LOCALAPPDATA) rather than its literal `%USERNAME%`.
    """
    candidates: list[str | None] = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    if sys.platform == "darwin":
        candidates += [
            "/Applications/Google Chrome.app",
            str(Path.home() / "Applications" / "Google Chrome.app"),
        ]
    elif sys.platform == "win32":
        candidates += [shutil.which("chrome"), shutil.which("chrome.exe")]
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            program_dir = os.environ.get(env_var)
            if program_dir:
                p = Path(program_dir, "Google", "Chrome", "Application", "chrome.exe")
                candidates.append(str(p))
    else:
        candidates += [
            "/usr/bin/google-chrome",
            "/usr/local/bin/google-chrome",
            "/opt/google/chrome/chrome",
            "/snap/bin/chromium",
        ]
    passed = any(c and Path(c).exists() for c in candidates)
    return DoctorCheck("chrome", "Google Chrome", passed, "found" if passed else "not found")


def check_alerts_json(state_dir: Path) -> DoctorCheck:
    p = state_dir / "alerts.json"
    if not p.exists():
        return DoctorCheck("alerts_json", "alerts.json", True, "not present")
    try:
        json.loads(p.read_text())
        return DoctorCheck("alerts_json", "alerts.json", True, "valid JSON")
    except json.JSONDecodeError as e:
        return DoctorCheck("alerts_json", "alerts.json", False, str(e)[:80])


def legacy_database_paths() -> list[Path]:
    """Where an install from before the rename and the E2 state-dir move can
    still be holding history: the old `PROJECT_ROOT/data/` file under either
    name, and anything in the old `~/.bike-tracker` state directory."""
    from findplus.config import PROJECT_ROOT

    paths = [
        PROJECT_ROOT / "data" / "findplus.sqlite",
        PROJECT_ROOT / "data" / "bike-tracker.sqlite",
    ]
    legacy_state = Path.home() / ".bike-tracker"
    if legacy_state.is_dir():
        paths.extend(sorted(legacy_state.glob("*.sqlite")))
    return paths


def check_legacy_database(current_db: Path) -> DoctorCheck:
    """Warn when readable history sits at a pre-rename path and is not in use.

    Find+ deliberately ships no automatic migration (PROMPT.md §1), so the
    check prints the two commands instead of moving anyone's data: copy the
    file into the state directory, or point FINDPLUS_DATABASE_PATH at it.
    """
    current = current_db.resolve() if current_db else None
    found = [
        p
        for p in legacy_database_paths()
        if p.is_file() and os.access(p, os.R_OK) and p.resolve() != current
    ]
    if not found:
        return DoctorCheck("legacy_database", "Legacy database", True, "none found")
    old = found[0]
    detail = (
        f"history found at {old} but Find+ is using {current_db}. "
        f"To keep it: cp '{old}' '{current_db}' "
        f"(or run with FINDPLUS_DATABASE_PATH='{old}'), then findplus db upgrade. "
        "Nothing is moved for you."
    )
    return DoctorCheck("legacy_database", "Legacy database", False, detail)


def check_desktop_app() -> DoctorCheck:
    if sys.platform != "darwin":
        return DoctorCheck("desktop_app", "Find+.app", True, "not applicable on this platform")
    installed = Path("/Applications/Find+.app").exists()
    return DoctorCheck(
        "desktop_app", "Find+.app", True, "installed" if installed else "not installed (optional)"
    )


def repair_db_head() -> None:
    from findplus.db.migrate import upgrade_to_head

    upgrade_to_head()


_REPAIRS: dict[str, object] = {
    "state_dir_perms": lambda settings: repair_state_dir_perms(settings.state_dir),
    "sensitive_file_perms": lambda settings: repair_sensitive_file_perms(settings.state_dir),
    "db_head": lambda settings: repair_db_head(),
}

_RERUN: dict[str, object] = {
    "state_dir_perms": lambda settings: check_state_dir_perms(settings.state_dir),
    "sensitive_file_perms": lambda settings: check_sensitive_file_perms(settings.state_dir),
    "db_head": lambda settings: check_db_head(),
}


@click.command("doctor")
@click.option("--repair", is_flag=True, help="Attempt automatic fixes for repairable checks.")
@click.option("--json", "json_flag", is_flag=True, help="Print machine-readable JSON.")
def doctor_cmd(repair: bool, json_flag: bool) -> None:
    """Diagnose the installation; with --repair, fix what can be fixed."""
    settings = get_settings()

    checks: list[DoctorCheck] = [
        check_python(),
        check_state_dir_perms(settings.state_dir),
        check_sensitive_file_perms(settings.state_dir),
        check_db_head(),
        check_providers(),
        check_units(),
        check_port(settings.state_dir, settings.port),
        check_chrome(),
        check_alerts_json(settings.state_dir),
        check_legacy_database(settings.database_path),
        check_desktop_app(),
    ]

    if repair:
        for i, c in enumerate(checks):
            if c.repairable and not c.passed and c.name in _REPAIRS:
                _REPAIRS[c.name](settings)  # type: ignore[operator]
                rerun = _RERUN[c.name](settings)  # type: ignore[operator]
                checks[i] = DoctorCheck(
                    rerun.name,
                    rerun.label,
                    rerun.passed,
                    rerun.detail,
                    repaired=True,
                    repairable=rerun.repairable,
                )

    if json_flag:
        click.echo(json.dumps([c.__dict__ for c in checks]))
        sys.exit(0 if all(c.passed for c in checks) else 1)

    for c in checks:
        sym = "✓" if c.passed else "✗"
        click.echo(f"{sym} {c.label}: {c.detail}")
    sys.exit(0 if all(c.passed for c in checks) else 1)

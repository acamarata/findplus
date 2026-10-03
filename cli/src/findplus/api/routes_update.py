"""Update routes: where the update stands, check now, and get ready to install.

Purpose    : GET /api/update/status for the dashboard banner and the desktop
             shell's tray item; POST /api/update/check for Check now; POST
             /api/update/apply, which only the desktop shell calls right before it
             runs update-app.sh.
Inputs     : `updates.auto` and `updates.dev_dir`; the X-FindPlus-Client header
             on apply.
Outputs    : The status body (updater/status.py); apply's {kind, path, version,
             backup, result_file}.
Constraints: status is reachable while the app is locked (the shell installs
             while locked) and names no paths or locations. apply is too, but
             only with the shell's header, so no web page can start an install;
             OriginGuardMiddleware already refuses foreign origins. check makes
             the one GitHub request even when `updates.auto` is off, because the
             owner pressed the button.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from findplus.config import get_settings
from findplus.db.session import session_scope
from findplus.updater import devsource, prefs
from findplus.updater.apply import prepare
from findplus.updater.check import start_check
from findplus.updater.release import UpdateError
from findplus.updater.status import can_install_here, status

#: The header the desktop shell sends on POST /api/update/apply, with this value.
SHELL_HEADER = "X-FindPlus-Client"
SHELL_HEADER_VALUE = "updater"


def _status_body() -> dict[str, Any]:
    with session_scope() as session:
        auto = prefs.auto_enabled(session)
    return status(get_settings().state_dir, auto=auto)


def get_status() -> dict[str, Any]:
    """Where the update stands: found, downloaded, ready, or blocked by a failed attempt."""
    return _status_body()


def post_check() -> dict[str, Any]:
    """Check GitHub (and the developer folder) now, in the background."""
    with session_scope() as session:
        dev_dir = devsource.dev_dir(session)
    start_check(get_settings().state_dir, download=can_install_here(), dev_dir=dev_dir)
    return _status_body()


def post_apply(request: Request) -> dict[str, Any]:
    """Verify the staged update and back up the database. Desktop shell only."""
    if request.headers.get(SHELL_HEADER) != SHELL_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="Only the Find+ app can install updates.")
    settings = get_settings()
    try:
        return prepare(settings.state_dir, settings.database_path, settings.effective_backup_dir)
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/update", tags=["updates"])
    router.add_api_route("/status", get_status, methods=["GET"])
    router.add_api_route("/check", post_check, methods=["POST"])
    router.add_api_route("/apply", post_apply, methods=["POST"])
    return router

"""Ask GitHub for the newest Find+ release and compare it with this one.

Purpose    : The single network question the updater asks: one GET to the GitHub
             releases API for acamarata/findplus. Nothing about the owner, their
             devices or their history is sent; the request carries only a
             User-Agent naming the Find+ version.
Inputs     : FINDPLUS_UPDATE_API (optional base URL; https, or http on a loopback
             address for tests), an optional httpx.Client.
Outputs    : A `Release` (version, page URL, dmg and .sha256 asset URLs) or None.
Constraints: Drafts and pre-releases are ignored. Version strings are compared
             numerically (1.10.0 > 1.9.0); a ".dev"/"rc" suffix sorts before the
             final release. Raises `UpdateError` with plain words, never anything
             else, so callers can show the message as is.
"""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

REPO = "acamarata/findplus"
DEFAULT_API = "https://api.github.com"
API_ENV = "FINDPLUS_UPDATE_API"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
#: The Apple Silicon disk image every release ships (`FindPlus-<ver>-aarch64.dmg`).
DMG_SUFFIX = "-aarch64.dmg"

_NUM = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$")


class UpdateError(RuntimeError):
    """An update step failed. The message is plain words, safe to show."""


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    page_url: str
    dmg_name: str | None
    dmg_url: str | None
    sha_url: str | None


def installed_version() -> str:
    """This Find+'s version, read at call time (tests replace `findplus.__version__`)."""
    import findplus

    return findplus.__version__


def version_key(text: str | None) -> tuple[int, int, int, int] | None:
    """(major, minor, patch, final) for comparing; None when it is not a version."""
    m = _NUM.match((text or "").strip())
    if not m:
        return None
    major, minor, patch, rest = m.groups()
    final = 1 if not rest else 0
    return (int(major), int(minor or 0), int(patch or 0), final)


def is_newer(candidate: str | None, current: str | None) -> bool:
    """True when `candidate` is a later version than `current`."""
    new, old = version_key(candidate), version_key(current)
    return new is not None and (old is None or new > old)


def _is_loopback(host: str | None) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def api_base() -> str:
    """The API base URL: GitHub, or FINDPLUS_UPDATE_API when it is safe to use."""
    raw = os.environ.get(API_ENV, "").strip().rstrip("/")
    if not raw:
        return DEFAULT_API
    parsed = urlparse(raw)
    if parsed.scheme == "https" or (parsed.scheme == "http" and _is_loopback(parsed.hostname)):
        return raw
    raise UpdateError(f"{API_ENV} must be an https address or a loopback address.")


def download_allowed(url: str | None) -> bool:
    """Assets come from this repository's GitHub releases (or the loopback test server)."""
    if not url:
        return False
    base = api_base()
    if base != DEFAULT_API:
        return urlparse(url).netloc == urlparse(base).netloc
    return url.startswith(f"https://github.com/{REPO}/releases/download/")


def parse_release(body: object) -> Release | None:
    """A published, final release from one releases/latest body, or None."""
    if not isinstance(body, dict) or body.get("draft") or body.get("prerelease"):
        return None
    version = str(body.get("tag_name") or "").lstrip("v")
    key = version_key(version)
    if key is None or key[3] == 0:
        return None
    assets = [a for a in body.get("assets") or [] if isinstance(a, dict)]
    by_name = {str(a.get("name")): str(a.get("browser_download_url") or "") for a in assets}
    dmg = next((n for n in by_name if n.endswith(DMG_SUFFIX)), None)
    return Release(
        version=version,
        page_url=str(body.get("html_url") or f"https://github.com/{REPO}/releases"),
        dmg_name=dmg,
        dmg_url=by_name.get(dmg) if dmg else None,
        sha_url=by_name.get(f"{dmg}.sha256") if dmg else None,
    )


def fetch_latest(client: httpx.Client | None = None) -> Release | None:
    """GET /repos/acamarata/findplus/releases/latest. None when there is no release."""
    url = f"{api_base()}/repos/{REPO}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"findplus/{installed_version()}",
    }
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        resp = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise UpdateError(f"Could not reach GitHub: {exc.__class__.__name__}.") from exc
    finally:
        if own:
            client.close()
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise UpdateError(f"GitHub answered {resp.status_code} to the update check.")
    try:
        return parse_release(resp.json())
    except ValueError as exc:
        raise UpdateError("GitHub sent an answer Find+ could not read.") from exc

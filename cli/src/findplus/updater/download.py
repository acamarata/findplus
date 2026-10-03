"""Download a release's disk image and keep it only when its sha256 matches.

Purpose    : Stage the new app in `<state>/updates/` so the desktop shell can
             install it later without another download.
Inputs     : A `Release` with dmg and .sha256 asset URLs; an httpx.Client.
Outputs    : {"path", "sha256", "version", "name"} for the staged dmg.
Constraints: Both URLs must be this repository's release assets (or the loopback
             test server). The image is written under a `.partial` name, hashed
             while it streams, and renamed into place only when the hash equals
             the published one; a mismatch deletes the partial file and installs
             nothing. A size cap stops a runaway download.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

import httpx

from findplus.updater.release import Release, UpdateError, download_allowed

#: No Find+ disk image comes close; anything bigger is not ours.
MAX_BYTES = 600 * 1024 * 1024
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_sha(text: str) -> str:
    """The hash in a `.sha256` file (`<hex>  <name>` or just `<hex>`)."""
    token = (text.split() or [""])[0].lower()
    if not _HEX64.match(token):
        raise UpdateError("The release's checksum file is not a sha256 checksum.")
    return token


def _stream_to(client: httpx.Client, url: str, temp: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    with client.stream("GET", url) as resp:
        if resp.status_code != 200:
            raise UpdateError(f"The download answered {resp.status_code}.")
        with temp.open("wb") as fh:
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UpdateError("The download is far larger than any Find+ app.")
                digest.update(chunk)
                fh.write(chunk)
    return digest.hexdigest()


def _fetch_sha(client: httpx.Client, url: str) -> str:
    resp = client.get(url)
    if resp.status_code != 200:
        raise UpdateError(f"The checksum download answered {resp.status_code}.")
    return expected_sha(resp.text)


def stage(release: Release, directory: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """Download and verify `release`'s dmg into `directory`. Raises UpdateError."""
    if not (release.dmg_name and release.dmg_url and release.sha_url):
        raise UpdateError("The newest release has no Apple Silicon app with a checksum.")
    if not (download_allowed(release.dmg_url) and download_allowed(release.sha_url)):
        raise UpdateError("The release points somewhere other than Find+'s GitHub releases.")
    name = Path(release.dmg_name).name
    final = directory / name
    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        want = _fetch_sha(client, release.sha_url)
        if final.exists() and sha256_of(final) == want:
            return {"path": str(final), "sha256": want, "version": release.version, "name": name}
        temp = directory / f"{name}.partial"
        try:
            got = _stream_to(client, release.dmg_url, temp)
            if got != want:
                raise UpdateError(
                    "The download did not match its published checksum, so it was thrown away."
                )
            if os.name != "nt":
                temp.chmod(0o600)
            os.replace(temp, final)
        finally:
            temp.unlink(missing_ok=True)
    except httpx.HTTPError as exc:
        raise UpdateError(f"The download failed: {exc.__class__.__name__}.") from exc
    finally:
        if own:
            client.close()
    return {"path": str(final), "sha256": want, "version": release.version, "name": name}

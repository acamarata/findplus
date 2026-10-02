#!/usr/bin/env python3
"""Generate the third-party notices file that the Find+ app bundle ships.

Purpose    : Attribution for everything that ends up inside the dmg: the
             vendored components plus the runtime dependency closure of
             `findplus[bundle,apple]` (what PyInstaller freezes into the
             sidecar). Dev tools (pytest, ruff, twine, ...) are not listed.
Inputs     : --out PATH (default desktop/src-tauri/notices/THIRD-PARTY-NOTICES.txt).
Outputs    : A plain-text file: vendored header, then one block per package
             with name, version, licence and the licence text found in its
             installed metadata.
Constraints: Run inside the project virtualenv with the `bundle` and `apple`
             extras installed (`pip install -e 'cli[bundle,apple]'`). Tauri
             ships the output as a bundle resource (tauri.conf.json).
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

ROOT_DIST = "findplus"
EXTRAS = ("bundle", "apple")
LICENSE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE)[^/]*$", re.IGNORECASE)
DEFAULT_OUT = "desktop/src-tauri/notices/THIRD-PARTY-NOTICES.txt"

HEADER = """Find+ third-party notices
=========================

Find+ is GPL-3.0-or-later. The app bundle includes the following third-party
components. Each keeps its own licence.

Vendored
--------
GoogleFindMyTools  GPL-3.0          https://github.com/leonboe1/GoogleFindMyTools
Leaflet 1.9.4      BSD-2-Clause     https://leafletjs.com
Lucide icons       ISC              https://lucide.dev

Python packages (runtime closure of findplus[bundle,apple])
-----------------------------------------------------------
PyInstaller is GPL-2.0-or-later with a bootloader exception that allows the
frozen app to carry any licence.
"""


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_closure() -> list[metadata.Distribution]:
    """Return the installed dists reachable from findplus + bundle + apple."""
    seen: dict[str, metadata.Distribution] = {}
    queue: list[tuple[str, tuple[str, ...]]] = [(ROOT_DIST, EXTRAS)]
    while queue:
        name, extras = queue.pop()
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        key = _norm(dist.metadata["Name"])
        if key in seen and key != ROOT_DIST:
            continue
        seen[key] = dist
        for raw in dist.requires or []:
            req = Requirement(raw)
            wanted = req.marker is None or any(
                req.marker.evaluate({"extra": e}) for e in (*extras, "")
            )
            if wanted:
                queue.append((req.name, tuple(req.extras)))
    seen.pop(ROOT_DIST, None)
    return sorted(seen.values(), key=lambda d: _norm(d.metadata["Name"]))


def licence_name(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    for field in ("License-Expression", "License"):
        value = (meta.get(field) or "").strip()
        if value and "\n" not in value and len(value) < 80:
            return value
    classes = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    return "; ".join(classes) or "see licence text"


def licence_text(dist: metadata.Distribution) -> str:
    for f in dist.files or []:
        if LICENSE_FILE.search(str(f)):
            try:
                raw = Path(dist.locate_file(f)).read_bytes()
            except OSError:
                continue
            if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                return raw.decode("utf-16", errors="replace").strip()
            return raw.replace(b"\x00", b"").decode("utf-8", errors="replace").strip()
    return "(no licence file in the installed package; see the project page)"


def render() -> str:
    parts = [HEADER]
    for dist in runtime_closure():
        name = dist.metadata["Name"]
        parts.append(
            f"\n{'=' * 72}\n{name} {dist.version}  ({licence_name(dist)})\n{'=' * 72}\n"
        )
        parts.append(licence_text(dist) + "\n")
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(), encoding="utf-8")
    print(f"Written to {out_path}")


if __name__ == "__main__":
    sys.exit(main())

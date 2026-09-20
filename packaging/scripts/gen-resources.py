"""Emit Homebrew `resource` stanzas for a findplus sdist's declared runtime
dependencies.

Purpose    : Fallback for gen-formula.sh when `brew update-python-resources`
             is unavailable or fails, so the generated formula never ships
             with the literal __RESOURCES__ token in it.
Inputs     : argv[1] = path to a findplus-<version>.tar.gz sdist.
Outputs    : Ruby `resource "<name>" do ... end` blocks on stdout, two-space
             indented, sorted by name, ready to splice into the template.
Constraints: Resolves the full transitive closure with pip's own resolver
             (`pip install --dry-run --report`) and asks PyPI for each
             resolved version's sdist url + sha256. A direct-dependency list
             is not enough: it installs and then crashes on the first
             transitive import (pydantic without pydantic_core, v1.0.0).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PYPI = "https://pypi.org/pypi/{name}/{version}/json"


def requirements(sdist: str) -> list[tuple[str, str]]:
    """Every package pip would install for `sdist`, as (name, version) pairs.

    pip resolves the whole graph; reading Requires-Dist would give the direct
    dependencies only, and Homebrew installs nothing that is not listed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--quiet",
                "--report",
                str(report),
                sdist,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not report.exists():
            raise SystemExit(
                f"gen-resources: pip could not resolve {sdist}\n{result.stderr}"
            )
        data = json.loads(report.read_text())
    pairs = []
    for item in data.get("install", []):
        meta = item.get("metadata", {})
        name, version = meta.get("name"), meta.get("version")
        if name and version and name.lower() != "findplus":
            pairs.append((name, version))
    return sorted(pairs, key=lambda pair: pair[0].lower())


def stanza(name: str, version: str) -> str | None:
    """Render the resource block for the exact version pip resolved."""
    with urllib.request.urlopen(
        PYPI.format(name=name, version=version), timeout=30
    ) as response:
        data = json.load(response)
    files = [f for f in data["urls"] if f["packagetype"] == "sdist"]
    if not files:
        print(f"gen-resources: no sdist on PyPI for {name} {version}", file=sys.stderr)
        return None
    chosen = files[0]
    return (
        f'  resource "{data["info"]["name"]}" do\n'
        f'    url "{chosen["url"]}"\n'
        f'    sha256 "{chosen["digests"]["sha256"]}"\n'
        f"  end\n"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: gen-resources.py <sdist-tarball>", file=sys.stderr)
        return 2
    blocks = [
        block
        for name, version in requirements(sys.argv[1])
        if (block := stanza(name, version))
    ]
    if not blocks:
        print("gen-resources: produced no resources", file=sys.stderr)
        return 1
    sys.stdout.write("\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

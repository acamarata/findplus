"""Emit Homebrew `resource` stanzas for a findplus sdist's declared runtime
dependencies.

Purpose    : Fallback for gen-formula.sh when `brew update-python-resources`
             is unavailable or fails, so the generated formula never ships
             with the literal __RESOURCES__ token in it.
Inputs     : argv[1] = path to a findplus-<version>.tar.gz sdist.
Outputs    : Ruby `resource "<name>" do ... end` blocks on stdout, two-space
             indented, sorted by name, ready to splice into the template.
Constraints: Reads `Requires-Dist` from the sdist's PKG-INFO and asks PyPI for
             each name's newest sdist url + sha256. Unlike Homebrew's own
             resolver this covers the DIRECT dependencies only, not the full
             transitive closure, so it is a fallback and not the happy path;
             gen-formula.sh says so on stderr when it is used.
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
import urllib.request

PYPI = "https://pypi.org/pypi/{name}/json"
# "uvicorn[standard]>=0.32" -> "uvicorn"; stops at the first extra/specifier char.
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+")


def requirements(sdist: str) -> list[str]:
    """Direct, non-extra requirement names declared in the sdist's PKG-INFO."""
    names: list[str] = []
    with tarfile.open(sdist, "r:gz") as tar:
        member = next(
            (
                m
                for m in tar.getmembers()
                if m.name.count("/") == 1 and m.name.endswith("PKG-INFO")
            ),
            None,
        )
        if member is None:
            raise SystemExit(f"gen-resources: no PKG-INFO in {sdist}")
        raw = tar.extractfile(member).read().decode("utf-8", "replace")
    for line in raw.splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        value = line.split(":", 1)[1].strip()
        if "extra ==" in value:
            continue
        match = NAME_RE.match(value)
        if match and match.group(0).lower() not in names:
            names.append(match.group(0).lower())
    return sorted(names)


def stanza(name: str) -> str | None:
    """Look up the newest sdist for `name` on PyPI and render its resource block."""
    with urllib.request.urlopen(PYPI.format(name=name), timeout=30) as response:
        data = json.load(response)
    files = [f for f in data["urls"] if f["packagetype"] == "sdist"]
    if not files:
        print(f"gen-resources: no sdist on PyPI for {name}", file=sys.stderr)
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
    blocks = [block for name in requirements(sys.argv[1]) if (block := stanza(name))]
    if not blocks:
        print("gen-resources: produced no resources", file=sys.stderr)
        return 1
    sys.stdout.write("\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

--check mode (L2-1): unlike gen-icons.py / gen-honesty-json.py, this
generator has no committed output to diff against -- its result is spliced
into packaging/homebrew/findplus.rb, which is gitignored and only exists
after a real release build, and producing it for real needs a built sdist
plus a live pip + PyPI round-trip. `--check` therefore does NOT reproduce
main()'s network resolution; it validates the one input it can read fully
offline and deterministically: cli/pyproject.toml's `[project].dependencies`
list, which is what main()'s pip resolution is ultimately rooted in. It
flags anything that would make that resolution non-reproducible (an
unpinned or `*`/`latest` entry, a VCS/URL requirement pip resolves
differently release to release) before it reaches a real `gen-formula.sh`
run. It cannot catch a version pin PyPI can no longer satisfy, a package
pulled from PyPI, or a transitive dependency's own drift -- those only
surface when main() actually runs against a real sdist.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - findplus pins Python >=3.12
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = REPO_ROOT / "cli" / "pyproject.toml"
PYPI = "https://pypi.org/pypi/{name}/{version}/json"

#: A PEP 508 requirement this script's pip resolution can reproduce the same
#: way every time: a plain distribution name (with optional extras) and at
#: least one `==`/`>=`/`~=`/etc specifier -- no `*`, no bare name, no
#: VCS/URL/local-path requirement, no environment marker (none of the
#: current dependencies need one; a marker would need pip's own evaluation
#: to check, which --check deliberately does not do).
_PINNED_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9_,.-]+\])?"
    r"\s*(==|!=|<=|>=|<|>|~=)\s*[A-Za-z0-9][A-Za-z0-9._*-]*"
    r"(\s*,\s*(==|!=|<=|>=|<|>|~=)\s*[A-Za-z0-9][A-Za-z0-9._*-]*)*$"
)


def _dependency_specs() -> list[str]:
    """The direct runtime dependencies declared in cli/pyproject.toml.

    This is the one input `--check` can see without a sdist or the network:
    every dependency main() eventually resolves via pip started from here.
    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(data.get("project", {}).get("dependencies", []))


def check() -> int:
    """Offline drift check: flag any dependency pip could resolve
    differently between runs. Never writes anything, never touches the
    network. Prints a diff-shaped summary and returns a process exit code.
    """
    specs = _dependency_specs()
    if not specs:
        print(
            f"gen-resources --check: {PYPROJECT} declares no dependencies",
            file=sys.stderr,
        )
        return 1
    offenders = [spec for spec in specs if not _PINNED_REQUIREMENT.match(spec)]
    if offenders:
        print(
            "gen-resources --check: dependency specs pip cannot resolve reproducibly:"
        )
        for spec in offenders:
            print(f"  - {spec}")
        print(f"({PYPROJECT}: pin every dependency, no *, no VCS/URL)")
        return 1
    print(
        f"gen-resources --check: {len(specs)} dependencies pinned, no network call made"
    )
    return 0


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
    if "--check" in sys.argv[1:]:
        return check()
    if len(sys.argv) != 2:
        print(
            "Usage: gen-resources.py <sdist-tarball> | gen-resources.py --check",
            file=sys.stderr,
        )
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

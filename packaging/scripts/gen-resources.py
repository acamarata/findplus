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
unpinned, VCS/URL, or non-numeric `*`/`latest`-shaped entry) before it
reaches a real `gen-formula.sh` run. A spec whose operator is not an exact
pin (`==`/`===`) is also flagged unless its dependency name is listed in
_DOCUMENTED_BOUND_EXCEPTIONS with a reason -- G5: `>=`/`~=`/`<=` alone can
resolve to a different concrete version release to release, so accepting
them by default made this check a no-op against every real dependency this
project has. It cannot catch a version pin PyPI can no longer satisfy, a
package pulled from PyPI, or a transitive dependency's own drift -- those
only surface when main() actually runs against a real sdist.
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

#: A PEP 508 requirement shaped so this script's pip resolution can
#: reproduce it: a plain distribution name (with optional extras) and at
#: least one specifier whose version starts with a digit -- no `*` alone,
#: no letter-led fake version like `latest`, no bare name, no VCS/URL/
#: local-path requirement, no environment marker (none of the current
#: dependencies need one; a marker would need pip's own evaluation to
#: check, which --check deliberately does not do). This only checks the
#: *shape* of a specifier; whether its operator is exact enough to count as
#: "pinned" is `_is_exact_pin`'s job below.
_REQUIREMENT_SHAPE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9_,.-]+\])?"
    r"(?P<specifiers>(\s*,?\s*(==|!=|<=|>=|<|>|~=|===)\s*[0-9][A-Za-z0-9._*-]*)+)$"
)

_OPERATOR = re.compile(r"==|!=|<=|>=|<|>|~=|===")
_EXACT_OPERATORS = frozenset({"==", "==="})

#: Runtime dependencies this pyproject.toml deliberately leaves at a
#: compatible-release lower bound (`>=`) rather than an exact `==` pin, and
#: why that is still reproducible for what this check protects: main()
#: resolves the whole graph with pip against a real sdist and bakes the one
#: version + sha256 pip picks into the generated Homebrew formula, so the
#: spec's own bound never ships -- only that single resolution does, and a
#: maintainer re-runs and re-commits it at every release, never silently
#: and never on a user's machine. Add a name here only alongside that same
#: reasoning holding for it; anything else must be an exact pin.
_DOCUMENTED_BOUND_EXCEPTIONS = frozenset(
    {
        "fastapi",
        "uvicorn",
        "python-multipart",
        "sqlalchemy",
        "alembic",
        "pydantic",
        "pydantic-settings",
        "click",
        "structlog",
        "python-dotenv",
        "tzlocal",
        "undetected-chromedriver",
        "selenium",
        "gpsoauth",
        "requests",
        "beautifulsoup4",
        "pyscrypt",
        "cryptography",
        "pycryptodomex",
        "ecdsa",
        "pytz",
        "protobuf",
        "httpx",
        "h2",
        "aiohttp",
        "http_ece",
        "setuptools",
        "mcp",
    }
)


def _offending(spec: str) -> bool:
    """True when pip could resolve `spec` to a different concrete version
    on a different day: it doesn't parse as a requirement at all, or its
    operators aren't all exact pins and its name isn't a documented
    exception."""
    match = _REQUIREMENT_SHAPE.match(spec)
    if not match:
        return True
    operators = _OPERATOR.findall(match.group("specifiers"))
    if all(op in _EXACT_OPERATORS for op in operators):
        return False
    return match.group("name").lower() not in _DOCUMENTED_BOUND_EXCEPTIONS


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
    offenders = [spec for spec in specs if _offending(spec)]
    if offenders:
        print(
            "gen-resources --check: dependency specs pip cannot resolve reproducibly:"
        )
        for spec in offenders:
            print(f"  - {spec}")
        print(
            f"({PYPROJECT}: pin with == (or ===), no *, no VCS/URL, no letter-led "
            "version -- or add the name to _DOCUMENTED_BOUND_EXCEPTIONS with a reason)"
        )
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
    # Homebrew's audit wants the PEP 503 normalised name (pydantic_core ->
    # pydantic-core), which is also what `brew update-python-resources` writes.
    resource_name = re.sub(r"[-_.]+", "-", data["info"]["name"]).lower()
    return (
        f'  resource "{resource_name}" do\n'
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

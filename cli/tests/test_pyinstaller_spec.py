"""The distributed app must not carry the repo's AI instruction files.

E1 packaging round 2 F4: the spec's datas entry was (ROOT/"web",
"findplus/web/static"), which copies the tree verbatim, dotdirs included. An
owner-run packaging/scripts/release-local.sh builds from the WORKING tree, so
the dmg embedded web/.claude/{AGENTS,CLAUDE}.md inside
Find+.app/.../_internal/findplus/web/static/.claude/. PRI rule 11 says .claude/
is never shipped; CI looked clean only because .claude/ is gitignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "packaging" / "pyinstaller"
SPECS = ("findplus-daemon.spec", "findplus-daemon-x86_64.spec")
SPEC = SPEC_DIR / SPECS[0]


def _expanded_datas(spec: Path | None = None) -> list[str]:
    """The spec's `datas`, expanded the way PyInstaller itself expands it."""
    format_binaries_and_datas = pytest.importorskip(
        "PyInstaller.building.utils"
    ).format_binaries_and_datas

    spec = spec or SPEC
    source = spec.read_text()
    body = source[source.index("ROOT = Path(SPECPATH)") : source.index("hiddenimports = [")]
    namespace: dict = {"Path": Path, "SPECPATH": str(spec.parent)}
    exec(body, namespace)
    return [dest for dest, _src in format_binaries_and_datas(namespace["datas"], str(spec.parent))]


@pytest.mark.parametrize("spec_name", SPECS)
def test_no_dotted_path_ships_under_the_dashboard(spec_name: str) -> None:
    """Both architectures. The filter lived only in the arm64 spec until
    security round 3 F3, so an Intel release shipped web/.claude/ inside the
    app -- where /static then served it."""
    dotted = [
        d
        for d in _expanded_datas(SPEC_DIR / spec_name)
        if d.startswith("findplus/web/static/") and any(p.startswith(".") for p in d.split("/"))
    ]
    assert dotted == [], f"{spec_name} would ship {dotted}"


def test_both_specs_ship_exactly_the_same_files() -> None:
    """They differ in target_arch only, so their datas must not drift again."""
    arm = sorted(_expanded_datas(SPEC_DIR / SPECS[0]))
    intel = sorted(_expanded_datas(SPEC_DIR / SPECS[1]))
    assert arm == intel


def test_the_dashboard_itself_still_ships() -> None:
    """The control: filtering must not empty the bundle."""
    datas = _expanded_datas()
    web = [d for d in datas if d.startswith("findplus/web/static/")]
    assert len(web) >= 20, f"only {len(web)} dashboard files would ship"
    assert any(d.startswith("findplus/web/static/app/") for d in web)
    assert any(d.startswith("findplus/web/static/partials/") for d in web), (
        "the composed partials must ship or / fails to start"
    )
    assert len([d for d in datas if d.startswith("findplus/db/migrations/")]) >= 8


@pytest.mark.parametrize("spec_name", SPECS)
def test_no_pycache_ships_from_any_tree(spec_name: str) -> None:
    """Local .pyc files are build-host junk; the vendored tree collected them too."""
    assert not [d for d in _expanded_datas(SPEC_DIR / spec_name) if "__pycache__" in d]


def test_the_vendor_closure_is_still_complete() -> None:
    """PRI rule 8: the vendored project ships intact, dotfiles and all.

    Only OUR trees lose their dotted paths. The vendor closure must keep
    matching `git ls-files`, which the wheel test pins at the same number.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "cli/vendor/GoogleFindMyTools"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout.split()
    bundled = [d for d in _expanded_datas() if d.startswith("findplus/_vendor/")]
    assert len(bundled) == len(tracked), f"vendor closure {len(bundled)} != {len(tracked)} tracked"

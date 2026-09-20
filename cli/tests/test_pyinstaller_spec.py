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
SPEC = ROOT / "packaging" / "pyinstaller" / "findplus-daemon.spec"


def _expanded_datas() -> list[str]:
    """The spec's `datas`, expanded the way PyInstaller itself expands it."""
    format_binaries_and_datas = pytest.importorskip(
        "PyInstaller.building.utils"
    ).format_binaries_and_datas

    source = SPEC.read_text()
    body = source[source.index("ROOT = Path(SPECPATH)") : source.index("hiddenimports = [")]
    namespace: dict = {"Path": Path, "SPECPATH": str(SPEC.parent)}
    exec(body, namespace)
    return [dest for dest, _src in format_binaries_and_datas(namespace["datas"], str(SPEC.parent))]


def test_no_dotted_path_ships_under_the_dashboard() -> None:
    dotted = [
        d
        for d in _expanded_datas()
        if d.startswith("findplus/web/static/") and any(p.startswith(".") for p in d.split("/"))
    ]
    assert dotted == [], f"the sidecar would ship {dotted}"


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


def test_no_pycache_ships_from_any_tree() -> None:
    """Local .pyc files are build-host junk; the vendored tree collected them too."""
    assert not [d for d in _expanded_datas() if "__pycache__" in d]


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

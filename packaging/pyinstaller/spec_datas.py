"""Which files each PyInstaller spec ships, and which it must not.

Purpose    : One definition of the datas walk, imported by BOTH
             findplus-daemon.spec (arm64) and findplus-daemon-x86_64.spec.
             The arm64 spec grew the filter for E1 packaging round 2 F4 and
             the Intel one did not, so an Intel release still embedded
             web/.claude/{AGENTS,CLAUDE}.md -- which the daemon then mounts at
             /static (E1 security round 3 F3). Two copies of a security filter
             is one copy too many.
Inputs     : The repo root, from the spec's SPECPATH.
Outputs    : A list of (source file, destination directory) pairs.
Constraints: Filtering changes what is PACKAGED, never the vendor tree itself
             (PRI rule 8), which is why the vendored project keeps its own
             dotfiles and loses only the __pycache__ a local run left behind.
"""

from __future__ import annotations

from pathlib import Path


def tree_datas(src_dir, dest_root: str, keep_dotted: bool = False):
    """Every file under `src_dir`, file by file, skipping caches and dotfiles.

    A bare (dir, dest) entry copies the tree verbatim, dotdirs included, and an
    owner-run release-local.sh builds from the WORKING tree, not a clean
    checkout. This is the same rel_parts test cli/hatch_build.py applies to the
    wheel.
    """
    out = []
    for file in sorted(Path(src_dir).rglob("*")):
        if not file.is_file():
            continue
        rel_parts = file.relative_to(src_dir).parts
        if "__pycache__" in rel_parts:
            continue
        if not keep_dotted and any(part.startswith(".") for part in rel_parts):
            continue
        out.append((str(file), "/".join((dest_root, *rel_parts[:-1]))))
    return out


def daemon_datas(root):
    """The three trees the sidecar ships, filtered."""
    root = Path(root)
    return [
        *tree_datas(root / "web", "findplus/web/static"),
        *tree_datas(root / "cli/src/findplus/db/migrations", "findplus/db/migrations"),
        *tree_datas(
            root / "cli/vendor/GoogleFindMyTools",
            "findplus/_vendor/GoogleFindMyTools",
            keep_dotted=True,
        ),
    ]

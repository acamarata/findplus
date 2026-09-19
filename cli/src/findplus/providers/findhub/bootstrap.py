"""Packaging bootstrap for the vendored GoogleFindMyTools tree.

Purpose : Resolve the on-disk location of GoogleFindMyTools and put it on
          sys.path, working in both an installed wheel and an editable
          dev checkout.
Inputs  : none.
Outputs : the resolved vendor Path, also inserted at sys.path[0].
Constraints:
    - sys.path-only. Does not touch credential storage — that is
      findplus.findhub.bootstrap:ensure_gfmt_importable (the E3 provider
      entry point, which also redirects secrets.json). The two are
      intentionally separate; do not merge or delete either.
    - Idempotent: safe to call repeatedly without duplicating sys.path entries.
"""

from __future__ import annotations

import importlib.resources as _ir
import sys
from pathlib import Path


def ensure_gfmt_importable() -> Path:
    """Add GoogleFindMyTools to sys.path[0] so it can be imported.
    Purpose: Resolve vendor path in both installed-wheel and dev-editable modes.
    Inputs: none.
    Outputs: resolved Path that was inserted into sys.path.
    Constraints: idempotent (checks sys.path before inserting); safe to call at module load.
    """
    # Path 1: inside the installed wheel at findplus/_vendor/
    pkg_vendor = Path(str(_ir.files("findplus").joinpath("_vendor/GoogleFindMyTools")))
    # Path 2: repo dev tree — 4 parents up from this file lands at cli/
    repo_vendor = Path(__file__).resolve().parents[4] / "vendor" / "GoogleFindMyTools"
    for candidate in (pkg_vendor, repo_vendor):
        if candidate.is_dir():
            target = str(candidate)
            if target not in sys.path:
                sys.path.insert(0, target)
            return candidate
    raise RuntimeError(
        f"GoogleFindMyTools not found at {pkg_vendor} or {repo_vendor}. "
        "Run: pip install -e 'cli/[dev]' from the repo root."
    )

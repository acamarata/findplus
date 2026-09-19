"""Packaging bootstrap for the vendored GoogleFindMyTools tree.

Purpose : Resolve the on-disk location of GoogleFindMyTools and put it on
          sys.path, working in both an installed wheel and an editable
          dev checkout.
Inputs  : none.
Outputs : the resolved vendor Path, also inserted at sys.path[0].
Constraints:
    - sys.path-only. Does not touch credential storage — that is
      findplus.providers.google_findhub.bootstrap:ensure_gfmt_importable (the
      provider entry point, which also redirects secrets.json). The two are
      intentionally separate; do not merge or delete either.
    - Idempotent: safe to call repeatedly without duplicating sys.path entries.
"""

from __future__ import annotations

import importlib.resources as _ir
import sys
from pathlib import Path


def _candidates() -> tuple[Path, Path]:
    # Path 1: inside the installed wheel at findplus/_vendor/
    pkg_vendor = Path(str(_ir.files("findplus").joinpath("_vendor/GoogleFindMyTools")))
    # Path 2: repo dev tree — 4 parents up from this file lands at cli/
    repo_vendor = Path(__file__).resolve().parents[4] / "vendor" / "GoogleFindMyTools"
    return pkg_vendor, repo_vendor


def resolve_vendor_path() -> Path:
    """Best-guess on-disk location of GoogleFindMyTools, no side effects.

    Purpose: give config.py a packaging-aware value for VENDOR_GFMT without
    mutating sys.path or raising when the tree is absent (e.g. in a test
    environment that never calls ensure_gfmt_importable).
    Inputs: none.
    Outputs: the packaged path if it exists, else the repo dev-tree path — the
    latter is returned even when absent, matching the previous unconditional
    VENDOR_GFMT constant so existing "not vendored" checks keep working.
    """
    pkg_vendor, repo_vendor = _candidates()
    return pkg_vendor if pkg_vendor.is_dir() else repo_vendor


def vendor_available() -> tuple[bool, str]:
    """Pure "could GoogleFindMyTools be imported?" probe.

    Purpose: let a read-only status query (`GET /api/providers`, `findplus
    providers`, `findplus doctor`) report availability without the side effects
    of `ensure_gfmt_importable()` — no sys.path mutation, no state-directory
    creation, no rebinding of the vendored credential store. Those belong to
    the code paths that actually talk to Google.
    Inputs: none.
    Outputs: (True, "") when a vendor tree exists, else (False, <reason>).
    """
    pkg_vendor, repo_vendor = _candidates()
    if any(candidate.is_dir() for candidate in (pkg_vendor, repo_vendor)):
        return (True, "")
    return (
        False,
        f"GoogleFindMyTools not found at {pkg_vendor} or {repo_vendor}. "
        "Run: pip install -e 'cli/[dev]' from the repo root.",
    )


def ensure_gfmt_importable() -> Path:
    """Add GoogleFindMyTools to sys.path[0] so it can be imported.
    Purpose: Resolve vendor path in both installed-wheel and dev-editable modes.
    Inputs: none.
    Outputs: resolved Path that was inserted into sys.path.
    Constraints: idempotent (checks sys.path before inserting); safe to call at module load.
    """
    pkg_vendor, repo_vendor = _candidates()
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

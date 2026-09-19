# Purpose: backward-compat shim for the pre-E3 findplus.findhub package.
# Inputs: none.
# Outputs: FindHubClient re-export; legacy submodule import paths restored.
# Constraints: findplus.providers.google_findhub is the real home (P1-E3-W3-S1-T2);
#              this module only aliases it so old import paths keep resolving.
"""Deprecated: import from findplus.providers.google_findhub instead.

The Google Find Hub client moved to `findplus.providers.google_findhub` in E3 so a
second provider (Apple Find My) could plug in beside it. This module restores the
legacy submodule import paths — `findplus.findhub.client`, `.types`, `.bootstrap` —
that several modules still import directly, and warns on import.
"""

from __future__ import annotations

import sys as _sys
import warnings

warnings.warn(
    "findplus.findhub is deprecated; import from findplus.providers.google_findhub instead.",
    DeprecationWarning,
    stacklevel=2,
)

from findplus.providers.google_findhub import bootstrap as _bootstrap  # noqa: E402
from findplus.providers.google_findhub import client as _client  # noqa: E402
from findplus.providers.google_findhub import types as _types  # noqa: E402
from findplus.providers.google_findhub.client import FindHubClient as FindHubClient  # noqa: E402

# Restore the legacy submodule paths so `from findplus.findhub.client import FindHubClient`
# (and .types / .bootstrap) keep resolving after the git mv.
_sys.modules.setdefault("findplus.findhub.client", _client)
_sys.modules.setdefault("findplus.findhub.types", _types)
_sys.modules.setdefault("findplus.findhub.bootstrap", _bootstrap)

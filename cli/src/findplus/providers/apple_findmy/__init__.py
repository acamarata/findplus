# Purpose: Apple Find My provider package for Find+ — availability guard.
# Inputs: none (probes sys.modules / import machinery only).
# Outputs: is_available() -> tuple[bool, str].
# Constraints: never imports findmy at module level, so this package loads even
#              when the optional `apple` extra is not installed.
"""Apple Find My provider package for Find+."""

from __future__ import annotations

import importlib

__all__ = ["is_available"]


def is_available() -> tuple[bool, str]:
    """Return (True, "") when the optional `findmy` dependency is importable.

    Uses importlib.import_module (not a bare `import findmy`) so this function
    can be called repeatedly with no module-level side effects and is mockable
    via sys.modules in tests without reloading this package.
    """
    try:
        importlib.import_module("findmy")
    except ImportError:
        return (False, "pip install 'findplus[apple]'")
    return (True, "")

# Purpose: Apple provider's own auth-required exception.
# Inputs: none.
# Outputs: AppleAuthRequiredError(Exception).
# Constraints: scoped to this package on purpose — never the same class as
#              findplus.findhub.types.AuthRequiredError (the Google provider's
#              exception); the two must stay distinct so an `except` on one
#              never swallows the other.
"""Apple Find My provider exceptions."""

from __future__ import annotations

__all__ = ["AppleAuthRequiredError"]


class AppleAuthRequiredError(Exception):
    """Raised when Apple Find My authentication is required before locate() can run."""

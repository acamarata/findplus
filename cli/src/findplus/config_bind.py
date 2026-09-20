"""What findplus is allowed to bind to (invariant I9).

Purpose    : One place that decides which bind addresses need the explicit
             opt-in, for the three entry points that can pick one. Split out
             of config.py so that file stays under the 300-line cap (PRI
             rule 7); config.py re-exports both names, so existing imports
             from findplus.config keep working.
Inputs     : A host string from `Settings.host`, `findplus config set HOST`
             or `findplus serve --host`.
Outputs    : LOOPBACK_HOSTS, is_public_bind().
Constraints: No import from findplus.config -- that would be circular.
"""

from __future__ import annotations

import os

#: The only hosts invariant I9 lets findplus bind without an explicit opt-in.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_public_bind(host: str) -> bool:
    """Whether binding `host` needs the FINDPLUS_ALLOW_PUBLIC_BIND opt-in.

    Purpose    : One place that decides what I9 allows, for the three entry
                 points that can pick a bind address.
    Inputs     : A host string from `Settings.host`, `findplus config set HOST`
                 or `findplus serve --host`.
    Outputs    : True when the bind must be refused.
    Constraints: Reads the environment on every call, never at import time, so
                 a test that sets the variable with monkeypatch takes effect.
                 Before this existed `serve --host` checked nothing, so
                 `config set HOST 0.0.0.0` refused while `serve --host 0.0.0.0`
                 silently bound every interface.
    """
    return host not in LOOPBACK_HOSTS and not _opted_in()


#: What counts as "yes" in FINDPLUS_ALLOW_PUBLIC_BIND.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _opted_in() -> bool:
    """Whether the opt-out of invariant I9 was actually asked for.

    This used to be a bare truthiness test on the variable, so
    FINDPLUS_ALLOW_PUBLIC_BIND=0 -- or "false", or "no", or "off" -- opted the
    user IN. Someone writing 0 to turn the override off turned it on, and the
    next FINDPLUS_HOST=0.0.0.0 put their location history on the LAN. Every
    other boolean setting is a pydantic bool that parses those correctly; this
    field inverted the convention on the strongest invariant in the app
    (E1 security round 3 F2).
    """
    return os.environ.get("FINDPLUS_ALLOW_PUBLIC_BIND", "").strip().lower() in _TRUTHY

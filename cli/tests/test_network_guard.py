"""Proves cli/tests/conftest.py's autouse socket guard actually blocks the network.

Purpose    : Verify a connect to a real internet host raises before any network I/O
             happens, and that loopback connects (what uvicorn/Playwright need) still
             work — so every other test file can trust the guard without re-testing it.
Inputs     : None (self-contained sockets; no fixtures beyond the autouse guard).
Outputs    : None (asserts / pytest.raises).
Constraints: Must never touch the real network, even to prove the block — the guarded
             `connect` raises before the underlying syscall runs.
"""

from __future__ import annotations

import socket

import pytest


def test_blocks_non_loopback_connect() -> None:
    """A connect to a real internet address raises, never reaching the network."""
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(RuntimeError, match="network access blocked in tests"),
    ):
        sock.connect(("93.184.216.34", 80))


def test_allows_loopback_connect() -> None:
    """A connect to a local listening socket on 127.0.0.1 is never blocked."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(("127.0.0.1", port))

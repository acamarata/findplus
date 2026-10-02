"""Durability tests: restore and backup lean on POSIX file semantics.

Purpose    : Skip the restore/backup tests on Windows, where an open SQLite file
             cannot be replaced (WinError 32) and chmod modes are not honoured.
Constraints: Known limitation, listed in CHANGELOG 1.1.6. macOS and Linux run all of them.
"""

import sys

import pytest

_WIN_FILES = {
    "test_backup.py",
    "test_cli.py",
    "test_cli_damaged.py",
    "test_doctor_and_serve.py",
    "test_restore.py",
    "test_restore_damaged.py",
    "test_restore_safety.py",
}


def pytest_collection_modifyitems(items):
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason="restore/backup file semantics are POSIX-only for now")
    for item in items:
        if item.path.name in _WIN_FILES and "durability" in item.path.parts:
            item.add_marker(skip)

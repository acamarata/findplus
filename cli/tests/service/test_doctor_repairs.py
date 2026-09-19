"""`findplus doctor`: state-dir and sensitive-file permission checks + repairs.

Split out of test_doctor.py (PRI rule 7, <=300 lines/file).
Constraints: Every check runs against tmp_path, never the real ~/.findplus.
"""

from __future__ import annotations

import os

import pytest

from findplus.cli.doctor import (
    check_sensitive_file_perms,
    check_state_dir_perms,
    repair_sensitive_file_perms,
    repair_state_dir_perms,
)


# ------------------------------------------------------------------------- b
@pytest.mark.posix_only
def test_check_state_dir_perms(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    assert check_state_dir_perms(tmp_path).passed is True

    os.chmod(tmp_path, 0o755)
    c = check_state_dir_perms(tmp_path)
    assert c.passed is False
    assert c.repairable is True


# ------------------------------------------------------------------------- c
@pytest.mark.posix_only
def test_check_sensitive_file_perms(tmp_path) -> None:
    secrets = tmp_path / "secrets.json"
    secrets.write_text("{}")
    os.chmod(secrets, 0o644)
    c = check_sensitive_file_perms(tmp_path)
    assert c.passed is False
    assert "secrets.json" in c.detail

    os.chmod(secrets, 0o600)
    assert check_sensitive_file_perms(tmp_path).passed is True


# ------------------------------------------------------------------------ c2
@pytest.mark.posix_only
def test_apple_key_store_is_covered(tmp_path) -> None:
    """PRI hard rule 9 / E11 review carry-forward #26: `apple/` is 0700 and each
    `apple/<device_id>.json` (a plist or a raw private key) is 0600."""
    apple = tmp_path / "apple"
    apple.mkdir(mode=0o700)
    key_file = apple / "apple-abc123.json"
    key_file.write_text("{}")
    os.chmod(key_file, 0o644)

    c = check_sensitive_file_perms(tmp_path)
    assert c.passed is False
    assert "apple-abc123.json" in c.detail

    repair_sensitive_file_perms(tmp_path)
    assert check_sensitive_file_perms(tmp_path).passed is True
    assert os.stat(key_file).st_mode & 0o777 == 0o600


@pytest.mark.posix_only
def test_apple_directory_mode_is_checked_and_repaired(tmp_path) -> None:
    apple = tmp_path / "apple"
    apple.mkdir()
    os.chmod(apple, 0o755)

    c = check_sensitive_file_perms(tmp_path)
    assert c.passed is False
    assert "0o700" in c.detail

    repair_sensitive_file_perms(tmp_path)
    assert os.stat(apple).st_mode & 0o777 == 0o700
    assert check_sensitive_file_perms(tmp_path).passed is True


# ------------------------------------------------------------------------- i
@pytest.mark.posix_only
def test_repair_state_dir_perms(tmp_path) -> None:
    os.chmod(tmp_path, 0o755)
    repair_state_dir_perms(tmp_path)
    assert (os.stat(tmp_path).st_mode & 0o777) == 0o700


# ------------------------------------------------------------------------- j
@pytest.mark.posix_only
def test_repair_sensitive_file_perms(tmp_path) -> None:
    p = tmp_path / "secrets.json"
    p.write_text("{}")
    os.chmod(p, 0o644)
    repair_sensitive_file_perms(tmp_path)
    assert (os.stat(p).st_mode & 0o777) == 0o600

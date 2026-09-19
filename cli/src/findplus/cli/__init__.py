"""Command line interface package.

Purpose    : Backward-compatible re-export so `from findplus.cli import main`
             keeps working after the split into findplus.cli.main:main.
Constraints: No command logic here — see main.py, cmd_service.py,
             cmd_diagnostics.py, cmd_devices.py, cmd_history.py.
"""

from findplus.cli.main import main

__all__ = ["main"]

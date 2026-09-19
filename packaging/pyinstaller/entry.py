"""PyInstaller entry point for the findplus-daemon sidecar.

Purpose    : Single importable script Analysis() can trace; delegates to the
             real CLI entry point so PyInstaller and `pip install` share one
             code path.
Inputs     : sys.argv (Click parses it inside main()).
Outputs    : Process exit code from findplus.cli.main:main.
Constraints: Must stay a plain script (no package __init__.py beside it) —
             PyInstaller's Analysis() traces it as a module, not a package.
"""

from findplus.cli.main import main

main()

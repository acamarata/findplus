"""PyInstaller entry point for the findplus-daemon sidecar.

Purpose    : Single importable script Analysis() can trace; delegates to the
             real CLI entry point so PyInstaller and `pip install` share one
             code path.
Inputs     : sys.argv (Click parses it inside main()).
Outputs    : Process exit code from findplus.cli.main:main.
Constraints: Must stay a plain script (no package __init__.py beside it) —
             PyInstaller's Analysis() traces it as a module, not a package.
             multiprocessing.freeze_support() must run before Click sees argv:
             Google sign-in's undetected_chromedriver starts Chrome through
             multiprocessing, which re-runs this frozen binary with its own
             bootstrap flags. Without it, Click rejected those flags, the
             child died with a broken pipe and Chrome never opened (v1.1.1).
"""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from findplus.cli.main import main

    main()

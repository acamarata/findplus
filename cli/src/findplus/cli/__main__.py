"""Lets `python -m findplus.cli` keep working after the module-to-package split.

Purpose    : Backward compatibility for anything (tests, docs, scripts) that
             invoked the pre-split `cli.py` module directly via `-m`.
"""

from findplus.cli.main import main

if __name__ == "__main__":
    main()

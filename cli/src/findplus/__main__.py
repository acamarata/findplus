"""Lets `python -m findplus` work the same as the installed `findplus` script.

Purpose    : Several tickets and docs invoke `python -m findplus <command>`
             directly against the venv without requiring an editable install
             to register the console_scripts entry point first.
"""

from findplus.cli.main import main

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate .github/docs/THIRD-PARTY.md from installed dependency licences.

Purpose    : Attribution required by GPL-3.0-or-later: list the licence of
             every vendored and runtime dependency.
Inputs     : --out PATH (default .github/docs/THIRD-PARTY.md).
Outputs    : A Markdown file with a vendored-component header plus the
             pip-licenses table for every installed Python package.
Constraints: Run inside the project virtualenv so it sees installed
             packages. GoogleFindMyTools is vendored, not a pip package, so
             it is listed manually in the header.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HEADER = """# Third-Party Licences

Find+ is GPL-3.0-or-later. It includes or depends on the following third-party components.

## Vendored

| Package | Licence | Source |
|---|---|---|
| GoogleFindMyTools | GPL-3.0 | https://github.com/leonboe1/GoogleFindMyTools |
| Leaflet | BSD-2-Clause | https://leafletjs.com |

## Python Dependencies

"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=".github/docs/THIRD-PARTY.md")
    args = parser.parse_args()

    pip_licenses = Path(sys.executable).parent / "pip-licenses"
    result = subprocess.run(
        [str(pip_licenses), "--format=markdown", "--with-license-file", "--no-license-path"],
        capture_output=True,
        text=True,
        check=True,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(HEADER + result.stdout, encoding="utf-8")
    print(f"Written to {out_path}")


if __name__ == "__main__":
    sys.exit(main())

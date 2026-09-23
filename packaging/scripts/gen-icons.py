"""Build the bundled Lucide sprite web/icons.svg from the vendored SVG files.

Purpose    : Turn packaging/vendor/lucide/<name>.svg plus the pinned index
             packaging/data/lucide-subset.json into one sprite document
             holding 48 <symbol> elements, so the dashboard fetches icon
             artwork exactly once and every <use href="#lucide-<name>">
             resolves against a symbol already in the page.
Inputs     : packaging/data/lucide-subset.json (owner: P2-E2-W2-S1-T1; read
             only, never written here) and the 48 vendored SVGs beside it.
             No network access at any point -- vendoring is a one-time
             manual step, not something this script does at run time.
Outputs    : web/icons.svg. With --check, nothing is written: the script
             compares the freshly rendered text against the committed file
             and exits 1 when they differ (the CI drift gate).
Constraints: stdlib only, same shape as gen-api-docs.py / gen-cli-docs.py.
             Each icon's stroke/fill attributes travel onto its <symbol>;
             width/height/xmlns/viewBox are dropped because the wrapper
             supplies them (a second viewBox would be a duplicate attribute,
             which is fatal to the DOMParser XML parse main.js performs).
SPORT      : master-inventories.md § Web components (P2-E3-W2-S1-T1).
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SUBSET = REPO_ROOT / "packaging" / "data" / "lucide-subset.json"
VENDOR_DIR = REPO_ROOT / "packaging" / "vendor" / "lucide"
OUTPUT = REPO_ROOT / "web" / "icons.svg"

_SVG_RE = re.compile(r"<svg\b([^>]*)>(.*)</svg>", re.DOTALL)

#: Attributes the wrapper re-states or the sprite root already carries.
#: viewBox is in this list for a reason: the <symbol> template below writes
#: its own, and XML parsing rejects a duplicate attribute outright.
_DROP_ATTRS = re.compile(r'\s(width|height|xmlns|viewBox)="[^"]*"')


def _symbol(name: str, group: str) -> str:
    """Wrap one vendored icon as a <symbol> carrying its subset group."""
    text = (VENDOR_DIR / f"{name}.svg").read_text(encoding="utf-8")
    text = re.sub(r"<\?xml[^>]*\?>\s*", "", text)
    match = _SVG_RE.search(text)
    if match is None:
        raise ValueError(f"{name}.svg holds no <svg> element")
    attrs, inner = match.groups()
    attrs = re.sub(r"\s+", " ", _DROP_ATTRS.sub("", attrs)).rstrip()
    return (
        f'<symbol id="lucide-{name}" data-group="{group}" viewBox="0 0 24 24"{attrs}>'
        f"{inner.strip()}</symbol>"
    )


def render() -> tuple[str, int]:
    """Return the whole sprite document and how many symbols it holds."""
    entries = json.loads(SUBSET.read_text(encoding="utf-8"))
    symbols = [_symbol(e["id"].split(":", 1)[1], e["group"]) for e in entries]
    # UAT2 N3: `style="display:none"` used to hide this root inline -- the
    # page's CSP has no 'unsafe-inline' in style-src, so the browser applies
    # neither the hiding NOR silence: it drops the attribute and logs a
    # violation on every load, from icon_sprite.js's DOMParser().parseFromString
    # call. components.css's `#fp-icon-sprite` rule already does the same
    # hiding (position/width/height/overflow) by id selector, so the inline
    # attribute was always redundant, never load-bearing.
    text = (
        '<svg id="fp-icon-sprite" xmlns="http://www.w3.org/2000/svg">\n'
        + "\n".join(symbols)
        + "\n</svg>\n"
    )
    return text, len(symbols)


def main(check: bool) -> int:
    new, count = render()
    if check:
        if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") == new:
            return 0
        print(
            "web/icons.svg is stale: run packaging/scripts/gen-icons.py",
            file=sys.stderr,
        )
        return 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(new, encoding="utf-8")
    print(f"Wrote web/icons.svg ({count} symbols)")
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:]))

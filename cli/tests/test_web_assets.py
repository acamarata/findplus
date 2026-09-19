"""Static-asset integrity guard for web/index.html and the app/ ES modules.

Purpose    : Catch a stale script tag or a /static/ reference that points at
             a file no longer on disk after the app.js -> app/*.js split.
Inputs     : web/index.html, parsed with stdlib html.parser (no third-party
             HTML-parsing dependency).
Outputs    : Assertions on the module entry point, the removed monolith tag,
             every /static/ reference's on-disk existence, and same-origin.
Constraints: No network access; everything is resolved against the repo tree.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
INDEX_HTML = REPO_ROOT / "web" / "index.html"


class _AssetCollector(HTMLParser):
    """Collects every script src= and link href= from the page."""

    def __init__(self) -> None:
        super().__init__()
        self.script_srcs: list[str] = []
        self.module_script_srcs: list[str] = []
        self.link_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "script" and attr_map.get("src"):
            self.script_srcs.append(attr_map["src"])
            if attr_map.get("type") == "module":
                self.module_script_srcs.append(attr_map["src"])
        elif tag == "link" and attr_map.get("href"):
            self.link_hrefs.append(attr_map["href"])


def _parse_index_html() -> _AssetCollector:
    parser = _AssetCollector()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return parser


def test_module_entry_point():
    parser = _parse_index_html()
    assert "/static/app/main.js" in parser.module_script_srcs


def test_old_appjs_removed():
    text = INDEX_HTML.read_text(encoding="utf-8")
    assert "/static/app.js" not in text


def test_static_assets_exist():
    parser = _parse_index_html()
    for src in [*parser.script_srcs, *parser.link_hrefs]:
        if not src.startswith("/static/"):
            continue
        on_disk = REPO_ROOT / "web" / src.removeprefix("/static/")
        assert on_disk.is_file(), f"missing static asset: {src} (expected at {on_disk})"


def test_no_external_scripts():
    parser = _parse_index_html()
    for src in [*parser.script_srcs, *parser.link_hrefs]:
        assert src.startswith("/") or src.startswith("./"), f"external asset reference: {src}"
        assert "://" not in src, f"external asset reference: {src}"


#: `import ... from "./x.js"` / `export ... from "./x.js"` inside web/app/*.js.
_RELATIVE_IMPORT = re.compile(r"""(?:^|\s)(?:import|export)\b[^;]*?from\s+["'](\.[^"']+)["']""")


def test_module_imports_resolve_on_disk():
    """A typo'd relative import is a blank page, and node --check cannot see it.

    `node --check` parses each file in isolation: it validates syntax but never
    resolves a specifier. Without this, `./lock.js` renamed to `./applock.js`
    would pass every gate in the suite and only fail in a browser.
    """
    app_dir = REPO_ROOT / "web" / "app"
    modules = sorted(app_dir.glob("*.js"))
    assert modules, f"no ES modules found under {app_dir}"
    for module in modules:
        for specifier in _RELATIVE_IMPORT.findall(module.read_text(encoding="utf-8")):
            target = (module.parent / specifier).resolve()
            assert target.is_file(), f"{module.name} imports missing module: {specifier}"

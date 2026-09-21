"""web/locales/en.json's generated blocks never drift from their sources.

Purpose    : honesty.py's NOTICES dict is the single source of truth for the
             sentences specs/honesty.md pins. The browser catalog carries a copy
             so the dashboard can render them without a round trip, and
             web/app/catalog-en.js carries a second copy as i18n.js's offline
             fallback. Both are generated; this test fails the moment either one
             stops matching its source.
Constraints: Reads the key set from `honesty.NOTICES` itself, never a retyped
             literal list, so a later ticket adding a sentence needs no change
             here — it only has to re-run
             packaging/scripts/gen-honesty-json.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from findplus import honesty

REPO_ROOT = Path(__file__).parent.parent.parent
CATALOG = REPO_ROOT / "web" / "locales" / "en.json"
FALLBACK = REPO_ROOT / "web" / "app" / "catalog-en.js"
WEB_APP = REPO_ROOT / "web" / "app"

#: What the generator wraps the catalog in, so the literal can be parsed as JSON.
_JS_PREFIX = "export const CATALOG_EN = "


def _camel(snake_id: str) -> str:
    """`lock_not_encryption` -> `lockNotEncryption`, the catalog's key style."""
    parts = snake_id.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _fallback_catalog() -> dict:
    """The CATALOG_EN literal out of catalog-en.js, parsed as JSON."""
    source = FALLBACK.read_text(encoding="utf-8")
    start = source.index(_JS_PREFIX) + len(_JS_PREFIX)
    return json.loads(source[start:].rstrip().rstrip(";"))


#: The namespaces specs/layout-i18n-a11y.md pins. `timeline` is an eleventh the
#: E9-T3 ticket names by key (`timeline.emptyDay` and friends); a later ticket may
#: add more, so this asserts the pinned set is PRESENT rather than exhaustive.
SPEC_NAMESPACES = (
    "common",
    "devices",
    "groups",
    "places",
    "alerts",
    "settings",
    "setup",
    "auth",
    "notices",
    "honesty",
)


def test_catalog_parses_and_has_every_namespace():
    data = _catalog()
    assert set(SPEC_NAMESPACES) <= set(data)
    assert list(data)[-1] == "honesty", "the generator rewrites honesty last, in place"
    for name, block in data.items():
        assert isinstance(block, dict), f"{name} must be a namespace object"


def test_honesty_block_matches_notices_value_for_value():
    honesty_block = _catalog()["honesty"]
    for notice_id, text in honesty.NOTICES.items():
        key = _camel(notice_id)
        assert key in honesty_block, f"en.json is missing honesty.{key}"
        assert honesty_block[key] == text, f"honesty.{key} does not match NOTICES[{notice_id!r}]"


def test_honesty_block_has_no_key_absent_from_notices():
    honesty_block = _catalog()["honesty"]
    assert set(honesty_block) == {_camel(key) for key in honesty.NOTICES}


def test_bundled_fallback_matches_the_json_catalog():
    """i18n.js's offline fallback is the same catalog, byte for byte."""
    assert _fallback_catalog() == _catalog()


#: A `t(` call whose first argument is one string literal -- never a
#: `+`-built dynamic key, which this test cannot check without a JS parser.
_T_CALL_RE = re.compile(r"\bt\(\s*[\"']([a-zA-Z0-9_.]+)[\"']\s*[,)]")


def _resolve(catalog: dict, key: str) -> str | None:
    """Walk a dot-path through `catalog`, mirroring i18n.js's resolve()."""
    node = catalog
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def test_every_static_t_call_key_resolves_in_the_catalog():
    """A literal `t("dotted.key")` whose key is missing from en.json renders
    the raw key on screen -- i18n.js's fallback-of-last-resort. This caught
    color-picker.js's default `customLabel` param calling `t("field.customColor")`
    with no `field` namespace in the catalog (loop-2 L2-8): the aria-label read
    "field.customColor" instead of "Custom colour" and no test noticed. Dynamic
    keys built with `+` (e.g. alerts_rules.js's `"alerts.channels." + id`) are
    skipped -- they cannot be resolved statically.
    """
    catalog = _catalog()
    missing = []
    for path in sorted(WEB_APP.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for match in _T_CALL_RE.finditer(text):
            key = match.group(1)
            if _resolve(catalog, key) is None:
                missing.append(f"{path.relative_to(REPO_ROOT)}: t({key!r})")
    assert not missing, "\n".join(missing)

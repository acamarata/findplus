"""The dashboard page is composed from its shell plus web/partials/ (CF-1).

Purpose    : index.html ran past the 300-line cap, so its tab panels and the
             Settings dialog body moved into partial files. Composition happens
             server-side: doing it in the browser would populate the DOM after
             first paint and break every script that reads its markup at parse
             time. These tests pin that the served page is whole, that the raw
             pieces are not published, and that a missing partial is loud.
Inputs     : The real web/ directory, plus a synthetic one under tmp_path.
Outputs    : pytest assertions on the composed HTML and on startup failure.
Constraints: No network, no database — compose_index only reads files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from findplus.api import STATIC_DIR
from findplus.web_compose import MissingPartialError, compose_index, partial_names

#: One element that only exists inside each partial, so its presence in the
#: composed page proves that partial was substituted rather than merely named.
_MARKER_ELEMENTS = {
    "dashboard": 'id="tracks"',
    "places": 'id="fp-add-place-btn"',
    "groups": 'id="fp-group-legend"',
    "alerts": 'id="fp-telegram-section"',
    "settings": 'id="setting-theme"',
}


def test_every_partial_is_substituted_into_the_page() -> None:
    html = compose_index(STATIC_DIR)

    for name, element in _MARKER_ELEMENTS.items():
        assert element in html, f"{name}.html was not composed into the page"


def test_the_composed_page_keeps_no_partial_markers() -> None:
    """A leftover marker means a substitution silently did not happen."""
    html = compose_index(STATIC_DIR)

    assert "@partial" not in html


def test_the_shell_names_exactly_the_partials_that_exist() -> None:
    names = partial_names(STATIC_DIR)

    assert sorted(names) == sorted(_MARKER_ELEMENTS)
    for name in names:
        assert (STATIC_DIR / "partials" / f"{name}.html").is_file()


def test_a_missing_partial_raises_instead_of_serving_a_hole(tmp_path: Path) -> None:
    """Fail at startup: a dashboard with an empty tab is worse than no start."""
    (tmp_path / "partials").mkdir()
    (tmp_path / "index.html").write_text(
        '<div id="tab-x"><!-- @partial: nonexistent --></div>', encoding="utf-8"
    )

    with pytest.raises(MissingPartialError, match="nonexistent"):
        compose_index(tmp_path)


def test_composition_is_substitution_only(tmp_path: Path) -> None:
    """Whatever surrounds a marker is preserved byte for byte."""
    (tmp_path / "partials").mkdir()
    (tmp_path / "partials" / "bit.html").write_text("<p>inner</p>", encoding="utf-8")
    (tmp_path / "index.html").write_text(
        "<main>\n  <!-- @partial: bit -->\n</main>\n", encoding="utf-8"
    )

    assert compose_index(tmp_path) == "<main>\n<p>inner</p></main>\n"

"""findplus.labels: validation tables, icon resolution, and the 0007 drift check.

Purpose : Pin the exact 422 messages the API returns, the four-form icon
          grammar, and the fact that migration 0007's private copy of the
          palette formula still agrees with the module's.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from findplus import labels

_MIGRATION = Path(labels.__file__).parent / "db" / "migrations" / "versions" / "0007_labels.py"


def _migration_module():
    """Load 0007 by path: its module name starts with a digit, so `import` cannot."""
    spec = importlib.util.spec_from_file_location("migration_0007", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("  Mom  ", "Mom"),
        ("x" * 40, "x" * 40),
        ("  " + "x" * 40 + "  ", "x" * 40),
    ],
)
def test_validate_label_accepts(raw: str | None, expected: str | None) -> None:
    assert labels.validate_label(raw) == expected


def test_validate_label_rejects_over_forty_characters() -> None:
    with pytest.raises(ValueError, match="label must be 40 characters or fewer"):
        labels.validate_label("x" * 41)


@pytest.mark.parametrize("icon", ["lucide:dog", "lucide:door-open", "letter:A", "letter", "none"])
def test_validate_icon_accepts_every_form(icon: str) -> None:
    assert labels.validate_icon(icon) == icon


@pytest.mark.parametrize(
    "icon",
    ["letter:AB", "letter:a", "LUCIDE:dog", "lucide:", "lucide:Dog", "", "letters", "none "],
)
def test_validate_icon_rejects_bad_grammar(icon: str) -> None:
    with pytest.raises(ValueError, match="icon must match lucide:"):
        labels.validate_icon(icon)


def test_validate_icon_rejects_an_unknown_lucide_id() -> None:
    with pytest.raises(ValueError, match="one of the available lucide icon ids"):
        labels.validate_icon("lucide:not-a-real-icon")


def test_validate_color_accepts_lowercase_hex() -> None:
    assert labels.validate_color("#4f8cf7") == "#4f8cf7"


@pytest.mark.parametrize("color", ["#4F8CF7", "#fff", "4f8cf7", "#4f8cf7f", "red"])
def test_validate_color_rejects(color: str) -> None:
    with pytest.raises(ValueError, match="color must be a lowercase #rrggbb hex value"):
        labels.validate_color(color)


@pytest.mark.parametrize(
    ("icon", "label", "name", "expected"),
    [
        ("letter:A", "Mom", "Tag 1", "A"),
        ("letter:7", None, "Tag 1", "7"),
        ("letter", "mom's keys", "Tag 1", "M"),
        ("letter", "   ", "fallback tag", "F"),
        ("letter", None, "  spaced  ", "S"),
        ("letter", "  ", "   ", None),
        ("lucide:dog", "Rex", "Tag 1", None),
        ("none", "Rex", "Tag 1", None),
    ],
)
def test_resolve_icon_letter(icon: str, label: str | None, name: str, expected: str | None) -> None:
    assert labels.resolve_icon_letter(icon, label, name) == expected


def test_lucide_subset_has_forty_eight_unique_ids() -> None:
    rows = labels.lucide_subset()
    assert len(rows) == 48
    ids = [row["id"] for row in rows]
    assert len(set(ids)) == 48
    assert all(row["id"].startswith("lucide:") for row in rows)
    assert {row["group"] for row in rows} == {"people", "pets", "things", "places"}


def test_palette_never_drifts_from_migration_0007() -> None:
    module = _migration_module()
    assert module.DEVICE_PALETTE == labels.DEVICE_PALETTE
    for n in range(20):
        device_id = f"sample-device-{n}"
        assert labels.palette_color_for(device_id) == module._palette_color(device_id)


def test_palette_never_drifts_from_the_widget_copy() -> None:
    """The Swift widget carries a third copy, for the R-P2-23 legacy default.

    `Model.swift:devicePalette` only ever renders a device row that a 1.0.x
    daemon sent without a `color`, so nothing fails loudly when it drifts —
    the badge just turns the wrong colour. This reads the literal back.
    """
    source = (
        Path(__file__).parents[2] / "desktop" / "widget" / "Sources" / "Model.swift"
    ).read_text(encoding="utf-8")
    literal = re.search(r"let devicePalette = \[(.*?)\]", source, re.DOTALL)
    assert literal, "Model.swift no longer declares devicePalette"
    assert re.findall(r"#[0-9a-f]{6}", literal.group(1)) == labels.DEVICE_PALETTE


def test_every_subset_id_is_sf_mapped_or_pinned_exempt() -> None:
    source = (
        Path(__file__).parents[2] / "desktop" / "widget" / "Sources" / "Views" / "ViewHelpers.swift"
    ).read_text(encoding="utf-8")
    table_match = re.search(r"let table: \[String: String\] = \[(.*?)\]", source, re.DOTALL)
    assert table_match, "ViewHelpers.swift no longer declares the SF symbol table"
    swift_mapped = set(re.findall(r'"([^"]+)":', table_match.group(1)))
    exempt = {"squirrel", "anchor"}
    
    python_ids = {row["id"].split(":", 1)[1] for row in labels.lucide_subset()}
    missing = python_ids - swift_mapped - exempt
    assert not missing, f"unmapped subset ids (not in Swift table or exempt set): {missing}"

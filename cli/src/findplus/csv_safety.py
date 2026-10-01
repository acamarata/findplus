"""Spreadsheet formula-injection guard shared by the CSV exporters."""

from __future__ import annotations

#: Characters a spreadsheet treats as the start of a formula.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> object:
    """Prefix a formula-leading cell with `'` so Excel/Sheets treat it as text.

    Device names come from the provider and from the user, so a name like
    `=HYPERLINK("http://…")` would otherwise execute the moment someone opened
    the export. The apostrophe is the documented spreadsheet escape and is not
    shown in the cell.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_LEAD):
        return "'" + value
    return value

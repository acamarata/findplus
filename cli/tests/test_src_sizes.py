"""The PRI rule-7 size caps, swept across the whole findplus package (E13 loop2 A3).

Sibling of test_api_sizes.py/test_web_sizes.py, but with no allowlist: the
per-module MODULES list this file used to carry ("only the CLI modules this
loop's items split") stopped meaningfully bounding anything once loop2 A3
found and fixed 17 real, silent, over-cap functions across mcp/, providers/,
groups/, alerts/, poller.py, timeline.py, cli/cmd_service.py and three
migrations -- exactly the failure mode test_api_sizes.py's own docstring
describes ("nothing failed when a build_router() grew a sixth handler"),
just outside api/'s walk. This walks every .py file under findplus/ (vendor
excluded: GoogleFindMyTools is upstream's code, never ours to cap) and fails
on the first function over 50 lines or file over 300, naming both.
"""

from __future__ import annotations

import ast
from pathlib import Path

import findplus

PACKAGE_DIR = Path(findplus.__file__).parent
FUNCTION_CAP = 50
FILE_CAP = 300


def _package_files() -> list[Path]:
    # Excludes both source layouts: the editable checkout imports findplus
    # straight from cli/src (no vendor code under it at all), while an
    # installed wheel force-includes GoogleFindMyTools at findplus/_vendor/
    # (see pyproject.toml [tool.hatch.build.targets.wheel.force-include]).
    # Skip any path with a "vendor" or "_vendor" segment so CI's site-packages
    # install and a local editable install are scanned identically.
    return [
        p
        for p in sorted(PACKAGE_DIR.rglob("*.py"))
        if "vendor" not in p.parts and "_vendor" not in p.parts
    ]


def _long_functions(tree: ast.Module) -> list[str]:
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > FUNCTION_CAP:
                offenders.append(f"{node.name} is {length} lines (cap {FUNCTION_CAP})")
    return offenders


def test_every_function_in_the_package_is_under_the_cap() -> None:
    offenders: list[str] = []
    for path in _package_files():
        offenders += [
            f"{path.relative_to(PACKAGE_DIR)}: {o}"
            for o in _long_functions(ast.parse(path.read_text(encoding="utf-8")))
        ]
    assert not offenders, "over-cap functions:\n" + "\n".join(offenders)


def test_every_file_in_the_package_is_under_the_cap() -> None:
    offenders = [
        f"{path.relative_to(PACKAGE_DIR)} is {len(path.read_text(encoding='utf-8').splitlines())} "
        f"lines (cap {FILE_CAP})"
        for path in _package_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > FILE_CAP
    ]
    assert not offenders, "over-cap files:\n" + "\n".join(offenders)

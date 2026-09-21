"""The PRI rule-7 size caps, enforced on the api package by AST (E13-CF-P2-13).

The 50-line function cap regressed five times in P2 because nothing failed
when a build_router() grew a sixth handler: the cap was a convention policed
by review, not a test. This walks every module in findplus/api/ and fails on
the first function over 50 lines or file over 300, naming both — a size lint
that cannot drift from the rule it enforces.
"""

from __future__ import annotations

import ast
from pathlib import Path

import findplus.api

API_DIR = Path(findplus.api.__file__).parent
FUNCTION_CAP = 50
FILE_CAP = 300


def _long_functions(tree: ast.Module) -> list[str]:
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > FUNCTION_CAP:
                offenders.append(f"{node.name} is {length} lines (cap {FUNCTION_CAP})")
    return offenders


def test_every_function_in_api_package_is_under_the_cap() -> None:
    offenders: list[str] = []
    for path in sorted(API_DIR.glob("*.py")):
        offenders += [f"{path.name}: {o}" for o in _long_functions(ast.parse(path.read_text()))]
    assert not offenders, "over-cap functions:\n" + "\n".join(offenders)


def test_every_file_in_api_package_is_under_the_cap() -> None:
    offenders = [
        f"{path.name} is {len(path.read_text().splitlines())} lines (cap {FILE_CAP})"
        for path in sorted(API_DIR.glob("*.py"))
        if len(path.read_text().splitlines()) > FILE_CAP
    ]
    assert not offenders, "over-cap files:\n" + "\n".join(offenders)

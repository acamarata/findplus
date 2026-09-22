"""The PRI rule-7 size caps, applied to the test tree itself (P2 E13 stage 1).

Sibling of test_src_sizes.py/test_api_sizes.py/test_web_sizes.py, but pointed
at cli/tests/ instead of findplus/: the cap has only ever been enforced on
shipped code, and the test tree has quietly grown its own over-cap files and
helper functions in the meantime (see
.claude/phases/current/p2/e13/tmp/tests-size-violations.md for the list this
test found on 2026-09-22). Both tests are xfail(strict=False) for now --
several agents are actively adding test files in the same tree and splitting
every offender out from under them would collide -- so this file's only job
right now is to report the current violation count without blocking anyone.
Stage 2 of this ticket removes the xfail once the violating files are split.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
FUNCTION_CAP = 50
FILE_CAP = 300


def _test_tree_files() -> list[Path]:
    return sorted(TESTS_DIR.rglob("*.py"))


def _long_functions(tree: ast.Module) -> list[str]:
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > FUNCTION_CAP:
                offenders.append(f"{node.name} is {length} lines (cap {FUNCTION_CAP})")
    return offenders


@pytest.mark.xfail(
    strict=False,
    reason="cli/tests has 18 over-cap functions as of 2026-09-22 (E13 stage 1 report); "
    "stage 2 splits them and removes this xfail",
)
def test_every_function_in_the_test_tree_is_under_the_cap() -> None:
    offenders: list[str] = []
    for path in _test_tree_files():
        offenders += [
            f"{path.relative_to(TESTS_DIR)}: {o}"
            for o in _long_functions(ast.parse(path.read_text(encoding="utf-8")))
        ]
    assert not offenders, "over-cap functions:\n" + "\n".join(offenders)


@pytest.mark.xfail(
    strict=False,
    reason="cli/tests has 6 over-cap files as of 2026-09-22 (E13 stage 1 report); "
    "stage 2 splits them and removes this xfail",
)
def test_every_file_in_the_test_tree_is_under_the_cap() -> None:
    offenders = [
        f"{path.relative_to(TESTS_DIR)} is {len(path.read_text(encoding='utf-8').splitlines())} "
        f"lines (cap {FILE_CAP})"
        for path in _test_tree_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > FILE_CAP
    ]
    assert not offenders, "over-cap files:\n" + "\n".join(offenders)

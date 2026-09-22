"""The PRI rule-7 size caps, applied to the test tree itself (P2 E13 stage 2).

Sibling of test_src_sizes.py/test_api_sizes.py/test_web_sizes.py, but pointed
at cli/tests/ instead of findplus/: the cap has only ever been enforced on
shipped code, and the test tree quietly grew its own over-cap files and
helper functions in the meantime.

Stage 1 (2026-09-22) reported 6 over-cap files and 18 over-cap functions
under `xfail`. Stage 2 split every one of those into siblings/helper modules
(see git log for `test: split <file>` and `test: shrink <function>` commits
the same day) and now enforces both caps for real. Four files were still
under active edit by other builders past the 3-hour wait this ticket
allows (test-infra/delivery-retry/UI builders), so they are named in the
allowlists below instead of silently skipped -- remove an entry only in the
same commit that actually splits/shrinks that file.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
FUNCTION_CAP = 50
FILE_CAP = 300

#: path (relative to cli/tests/) -> why it isn't split yet.
FILE_CAP_ALLOWLIST: dict[str, str] = {
    "service/test_service_cmds.py": (
        "E13 stage 2 (2026-09-22): over cap and under active edit by another "
        "builder past the 3-hour wait; split it and remove this entry."
    ),
    "ui/test_places.py": (
        "E13 stage 2 (2026-09-22): over cap and under active edit by another "
        "builder past the 3-hour wait; split it and remove this entry."
    ),
}

#: (path relative to cli/tests/, function name) -> why it isn't shrunk yet.
FUNCTION_CAP_ALLOWLIST: dict[tuple[str, str], str] = {
    ("test_api_routes_snapshot.py", "test_route_paths_present"): (
        "E13 stage 2 (2026-09-22): over cap and under active edit by another "
        "builder past the 3-hour wait; shrink it and remove this entry."
    ),
    ("ui/test_setup_wizard.py", "test_devices_step_done_count_reflects_what_was_just_tracked"): (
        "E13 stage 2 (2026-09-22): over cap and under active edit by another "
        "builder past the 3-hour wait; shrink it and remove this entry."
    ),
}


def _test_tree_files() -> list[Path]:
    return sorted(TESTS_DIR.rglob("*.py"))


def _long_functions(tree: ast.Module) -> list[tuple[str, int]]:
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > FUNCTION_CAP:
                offenders.append((node.name, length))
    return offenders


def test_every_function_in_the_test_tree_is_under_the_cap() -> None:
    offenders: list[str] = []
    for path in _test_tree_files():
        rel = str(path.relative_to(TESTS_DIR))
        for name, length in _long_functions(ast.parse(path.read_text(encoding="utf-8"))):
            if (rel, name) in FUNCTION_CAP_ALLOWLIST:
                continue
            offenders.append(f"{rel}: {name} is {length} lines (cap {FUNCTION_CAP})")
    assert not offenders, "over-cap functions:\n" + "\n".join(offenders)


def test_every_file_in_the_test_tree_is_under_the_cap() -> None:
    offenders: list[str] = []
    for path in _test_tree_files():
        rel = str(path.relative_to(TESTS_DIR))
        if rel in FILE_CAP_ALLOWLIST:
            continue
        n = len(path.read_text(encoding="utf-8").splitlines())
        if n > FILE_CAP:
            offenders.append(f"{rel} is {n} lines (cap {FILE_CAP})")
    assert not offenders, "over-cap files:\n" + "\n".join(offenders)

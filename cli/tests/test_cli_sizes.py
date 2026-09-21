"""The PRI rule-7 size caps on the CLI modules this loop's items split.

Sibling of test_api_sizes.py: the same AST check, scoped to the cli/ command
modules this loop's items refactored, so the 50-line cap holds on them even
though the wider findplus package still carries off-worklist offenders owned
by other tickets.
"""

from __future__ import annotations

import ast
from importlib import import_module

import pytest

FUNCTION_CAP = 50
FILE_CAP = 300

MODULES = [
    "findplus.cli.cmd_devices",
    "findplus.cli.cmd_serve",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_functions_are_under_the_cap(module_name: str) -> None:
    module = import_module(module_name)
    source = open(module.__file__, encoding="utf-8")  # noqa: SIM115 - test reads once, immediately
    with source:
        tree = ast.parse(source.read())
    offenders = [
        f"{node.name} is {node.end_lineno - node.lineno + 1} lines (cap {FUNCTION_CAP})"
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.end_lineno - node.lineno + 1 > FUNCTION_CAP
    ]
    assert not offenders, "over-cap functions:\n" + "\n".join(offenders)


@pytest.mark.parametrize("module_name", MODULES)
def test_module_file_is_under_the_cap(module_name: str) -> None:
    module = import_module(module_name)
    count = len(open(module.__file__, encoding="utf-8").read().splitlines())  # noqa: SIM115
    assert count <= FILE_CAP, f"{module_name} is {count} lines (cap {FILE_CAP})"

"""select_shard splits a collection by whole files into disjoint, complete shards."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._shard import select_shard


def _items(sizes: dict[str, int]) -> list[SimpleNamespace]:
    return [SimpleNamespace(path=Path(f), n=i) for f, size in sizes.items() for i in range(size)]


def _run(monkeypatch: pytest.MonkeyPatch, spec: str | None, items: list) -> list:
    monkeypatch.delenv("FINDPLUS_TEST_SHARD", raising=False)
    if spec:
        monkeypatch.setenv("FINDPLUS_TEST_SHARD", spec)
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda items: None))
    kept = list(items)
    select_shard(config, kept)  # type: ignore[arg-type]
    return kept


def test_shards_are_disjoint_complete_and_keep_files_whole(monkeypatch) -> None:
    items = _items({"a.py": 9, "b.py": 5, "c.py": 4, "d.py": 3, "e.py": 3, "f.py": 1})
    shards = [_run(monkeypatch, f"{i}/3", items) for i in (1, 2, 3)]
    assert sorted(id(x) for s in shards for x in s) == sorted(id(x) for x in items)
    files = [{x.path for x in s} for s in shards]
    assert not (files[0] & files[1] or files[0] & files[2] or files[1] & files[2])
    assert max(len(s) for s in shards) - min(len(s) for s in shards) <= 4


def test_no_spec_keeps_everything(monkeypatch) -> None:
    items = _items({"a.py": 2, "b.py": 2})
    assert _run(monkeypatch, None, items) == items


def test_a_bad_index_is_a_usage_error(monkeypatch) -> None:
    with pytest.raises(pytest.UsageError):
        _run(monkeypatch, "5/4", _items({"a.py": 1}))

"""Split one pytest selection across CI shards by test file.

Purpose    : The browser lane ran ~1000 tests serially for 33 minutes. With
             FINDPLUS_TEST_SHARD="2/4" a runner keeps the files assigned to
             shard 2 of 4 and deselects the rest, so a CI matrix runs the lane
             in parallel on separate runners.
Inputs     : FINDPLUS_TEST_SHARD ("<index>/<count>", 1-based); unset = no sharding.
Outputs    : `select_shard(config, items)` trims `items` in place.
Constraints: Whole files stay together (module and session fixtures start one
             server per file group). Assignment is deterministic and depends only
             on the collected items, so every shard sees the same split.
"""

from __future__ import annotations

import os
from collections import defaultdict

import pytest


def _parse(spec: str) -> tuple[int, int]:
    index, _, count = spec.partition("/")
    shard, total = int(index), int(count)
    if not 1 <= shard <= total:
        raise pytest.UsageError(f"FINDPLUS_TEST_SHARD={spec!r}: need 1 <= index <= count")
    return shard, total


def select_shard(config: pytest.Config, items: list[pytest.Item]) -> None:
    spec = os.environ.get("FINDPLUS_TEST_SHARD")
    if not spec:
        return
    shard, total = _parse(spec)
    by_file: dict[str, list[pytest.Item]] = defaultdict(list)
    for item in items:
        by_file[str(item.path)].append(item)
    # Largest files first onto the lightest shard (ties: lowest shard, then path).
    loads = [0] * total
    owner: dict[str, int] = {}
    for path, group in sorted(by_file.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        target = loads.index(min(loads))
        owner[path] = target + 1
        loads[target] += len(group)
    kept = [i for i in items if owner[str(i.path)] == shard]
    dropped = [i for i in items if owner[str(i.path)] != shard]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept

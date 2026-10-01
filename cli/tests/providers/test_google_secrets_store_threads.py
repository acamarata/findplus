"""secrets.json is read and written under one lock, at the state dir in force per call.

Review r1 #12/#13: the vendored set_cached_value reads, truncates and rewrites in
place; poll-thread token caching racing a helper /unlock could drop `shared_key`,
and a reader during the truncate saw invalid JSON.
"""

from __future__ import annotations

import json
import threading

from findplus.providers.google_findhub.bootstrap import ensure_gfmt_importable


def test_concurrent_writers_keep_every_key(tmp_db) -> None:
    ensure_gfmt_importable()
    import Auth.token_cache as token_cache

    errors: list[BaseException] = []

    def write(prefix: str) -> None:
        try:
            for i in range(60):
                token_cache.set_cached_value(f"{prefix}{i}", "v")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(p,)) for p in ("a", "b", "c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    from findplus.config import get_settings

    data = json.loads(get_settings().secrets_file.read_text())
    assert len([k for k in data if k[0] in "abc" and k[1:].isdigit()]) == 180


def test_a_reader_never_sees_half_a_file(tmp_db) -> None:
    ensure_gfmt_importable()
    import Auth.token_cache as token_cache

    from findplus.providers.google_findhub import bootstrap

    token_cache.set_cached_value("shared_key", "keep-me")
    stop = threading.Event()
    seen_missing: list[bool] = []

    def churn() -> None:
        i = 0
        while not stop.is_set():
            token_cache.set_cached_value("noise", str(i))
            i += 1

    thread = threading.Thread(target=churn)
    thread.start()
    try:
        for _ in range(300):
            if (bootstrap._read_store() or {}).get("shared_key") != "keep-me":
                seen_missing.append(True)
            if token_cache.get_cached_value("shared_key") != "keep-me":
                seen_missing.append(True)
    finally:
        stop.set()
        thread.join()
    assert seen_missing == []

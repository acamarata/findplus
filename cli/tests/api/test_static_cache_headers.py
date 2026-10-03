"""The page and its scripts are revalidated, never served stale after an update."""

from fastapi.testclient import TestClient

from findplus.api import create_app


def test_page_and_static_files_say_no_cache(tmp_db) -> None:
    client = TestClient(create_app())
    for path in ("/", "/static/app/suspect_controls.js"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["cache-control"] == "no-cache", path

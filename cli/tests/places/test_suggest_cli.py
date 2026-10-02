"""`findplus places suggest` on the synthetic family."""

from __future__ import annotations

import json

from click.testing import CliRunner

from findplus.cli.main import main
from tests.places import test_suggest_api as seeded


def test_table_shows_questions_not_names(tmp_db) -> None:
    seeded._seed()
    out = CliRunner().invoke(
        main, ["places", "suggest", "--timezone", "UTC", "--date", seeded.LAST_DAY, "--json"]
    )
    assert out.exit_code == 0, out.output
    kinds = [c["kind_guess"] for c in json.loads(out.output)]
    assert kinds[0] == "home" and len(kinds) == 3

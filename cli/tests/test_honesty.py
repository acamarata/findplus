"""honesty.py constants match specs/honesty.md character-for-character.

Build-notes carry-forward #28: the six sentences must have exactly one
code-side source of truth (honesty.py) to drift from the spec file, and that
mirror needs its own regression test rather than relying on the API test
(test_core_endpoints.py::test_config_notices) to catch a future divergence.
"""

from __future__ import annotations

import re
from pathlib import Path

from findplus import honesty

_SPEC_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".claude"
    / "phases"
    / "current"
    / "p1"
    / "specs"
    / "honesty.md"
)
_LINE_RE = re.compile(r'^- (\w+): "(.+?)"')


def _spec_sentences() -> dict[str, str]:
    sentences: dict[str, str] = {}
    for line in _SPEC_PATH.read_text(encoding="utf-8").splitlines():
        match = _LINE_RE.match(line)
        if match:
            sentences[match.group(1)] = match.group(2)
    return sentences


def test_every_constant_matches_the_spec_verbatim() -> None:
    spec = _spec_sentences()
    assert set(spec) == set(honesty.NOTICES)
    for key, sentence in spec.items():
        assert honesty.NOTICES[key] == sentence, key


def test_notices_dict_matches_named_constants() -> None:
    assert honesty.NOTICES == {
        "find_hub": honesty.FIND_HUB,
        "apple": honesty.APPLE,
        "alerts_latency": honesty.ALERTS_LATENCY,
        "presence_stale": honesty.PRESENCE_STALE,
        "lock_not_encryption": honesty.LOCK_NOT_ENCRYPTION,
        "not_affiliated": honesty.NOT_AFFILIATED,
    }

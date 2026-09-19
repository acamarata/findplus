"""honesty.py constants match specs/honesty.md character-for-character.

Build-notes carry-forward #28: the six sentences must have exactly one
code-side source of truth (honesty.py) to drift from the spec file, and that
mirror needs its own regression test rather than relying on the API test
(test_core_endpoints.py::test_config_notices) to catch a future divergence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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

#: `.claude/` is gitignored (PRI rule 11), so the spec file is present in a dev
#: checkout and absent in a clean clone, an sdist and CI. Comparing against it is
#: the point of this module, so skip rather than fail where it cannot exist —
#: `test_notices_dict_matches_named_constants` still runs everywhere.
_needs_spec = pytest.mark.skipif(
    not _SPEC_PATH.exists(), reason="specs/honesty.md is only present in a dev checkout"
)


def _spec_sentences() -> dict[str, str]:
    sentences: dict[str, str] = {}
    for line in _SPEC_PATH.read_text(encoding="utf-8").splitlines():
        match = _LINE_RE.match(line)
        if match:
            sentences[match.group(1)] = match.group(2)
    return sentences


@_needs_spec
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


def test_no_module_re_types_an_honesty_sentence() -> None:
    """Every surface must reference honesty.py, never carry its own copy.

    `api/__init__.py` held a second, hand-typed literal of the Find Hub
    paragraph that `/api/health`, `/api/config` and `/api/status` served. It
    happened to match, but nothing compared the two: an edit to
    specs/honesty.md would have updated honesty.py (which
    test_every_constant_matches_the_spec_verbatim checks) and left three API
    surfaces quietly serving the old wording. This asserts the alias, and
    catches any new copy pasted into cli/src.
    """
    import re
    from pathlib import Path

    from findplus.api import FIND_HUB_NOTICE

    assert FIND_HUB_NOTICE is honesty.FIND_HUB

    # The distinctive tail of each sentence, so a copy anywhere in cli/src is found.
    fingerprints = {
        "find_hub": "child-safety GPS tracking",
        "apple": "which most users cannot do",
        "lock_not_encryption": "Use FileVault",
        "presence_stale": "reports it as unknown",
        "not_affiliated": "are their trademarks",
    }
    src = Path(honesty.__file__).parent
    allowed = {src / "honesty.py"}
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        if path in allowed or "_vendor" in path.parts or "vendor" in path.parts:
            continue
        body = path.read_text(encoding="utf-8")
        # Strip docstrings/comments: prose ABOUT a rule is not a second copy of it.
        code = re.sub(r'""".*?"""', "", body, flags=re.S)
        code = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
        for key, tail in fingerprints.items():
            if tail in code:
                offenders.append(f"{path.relative_to(src)}: {key}")
    assert not offenders, f"honesty sentence re-typed instead of imported: {offenders}"

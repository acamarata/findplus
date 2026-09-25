"""gen-resources.py --check flags dependency drift without pip or the network.

Purpose    : L2-1. Unlike gen-icons.py/gen-honesty-json.py there is no
             committed generated file to diff (the real output is spliced
             into the gitignored packaging/homebrew/findplus.rb by
             gen-formula.sh, which needs a built sdist and PyPI). `--check`
             instead validates the one input it can read offline:
             cli/pyproject.toml's `[project].dependencies` list.
Inputs     : A tmp_path pyproject.toml, monkeypatched over the module's
             PYPROJECT constant, plus the real cli/pyproject.toml.
Outputs    : Assertions only. Nothing is written; urlopen is patched to
             raise, proving --check never touches the network.
Constraints: gen-resources.py lives outside the findplus package with a
             hyphenated filename, so it is loaded via importlib, same as
             test_gen_icons.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "packaging" / "scripts"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_resources", SCRIPTS_DIR / "gen-resources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_pyproject(tmp_path: Path, deps: list[str]) -> Path:
    body = "".join(f'  "{d}",\n' for d in deps)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "findplus"\ndependencies = [\n{body}]\n',
        encoding="utf-8",
    )
    return tmp_path / "pyproject.toml"


def _no_network(monkeypatch, module: ModuleType) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("--check must never touch the network")

    monkeypatch.setattr(module.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("--check must never run pip")),
    )


def test_check_passes_on_the_real_pyproject(monkeypatch) -> None:
    """The committed cli/pyproject.toml is exactly what this guards -- it
    must already be clean, offline, with no network call.
    """
    module = _load()
    _no_network(monkeypatch, module)
    assert module.check() == 0


def test_check_flags_an_unpinned_dependency(tmp_path, monkeypatch) -> None:
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, ["fastapi", "click>=8.1"]))
    assert module.check() == 1


def test_check_flags_a_vcs_or_url_dependency(tmp_path, monkeypatch) -> None:
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "PYPROJECT",
        _write_pyproject(tmp_path, ["fastapi @ git+https://example.com/fastapi.git"]),
    )
    assert module.check() == 1


def test_check_flags_a_bare_wildcard_version(tmp_path, monkeypatch) -> None:
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, ["fastapi==*"]))
    assert module.check() == 1


def test_check_accepts_a_compatible_release_wildcard(tmp_path, monkeypatch) -> None:
    """`==1.2.*` is a real, reproducible PEP 440 specifier, not a bare `*`."""
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, ["fastapi==1.2.*"]))
    assert module.check() == 0


def test_check_flags_an_empty_dependency_list(tmp_path, monkeypatch) -> None:
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, []))
    assert module.check() == 1


def test_main_dispatches_check_without_requiring_a_sdist_argument(monkeypatch) -> None:
    """The original bug: `gen-resources.py --check` was treated as the sdist
    positional argument and failed inside pip's resolver.
    """
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module.sys, "argv", ["gen-resources.py", "--check"])
    assert module.main() == 0


def test_check_flags_an_undocumented_lower_bound(tmp_path, monkeypatch) -> None:
    """G5: `>=` (and `~=`/`<=`) used to be accepted from any dependency. A
    name not in _DOCUMENTED_BOUND_EXCEPTIONS must now fail --check."""
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, ["not-a-real-dep>=1.0"]))
    assert module.check() == 1


def test_check_accepts_a_documented_lower_bound(tmp_path, monkeypatch) -> None:
    """The other half of G5: a name that IS in _DOCUMENTED_BOUND_EXCEPTIONS
    (every current real runtime dependency is) still passes with `>=`."""
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, ["fastapi>=0.115"]))
    assert module.check() == 0


def test_check_flags_a_letter_led_fake_version(tmp_path, monkeypatch) -> None:
    """G5: `foo==latest` used to match the old regex's alnum-led version
    class even though "latest" is not a PEP 440 version pip can reproduce."""
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, ["fastapi==latest"]))
    assert module.check() == 1


def test_check_accepts_a_documented_multi_specifier_bound(tmp_path, monkeypatch) -> None:
    """The real project's `mcp>=2.2,<3` shape: two non-exact operators on a
    documented name must still pass, comma and all."""
    module = _load()
    _no_network(monkeypatch, module)
    monkeypatch.setattr(module, "PYPROJECT", _write_pyproject(tmp_path, ["mcp>=2.2,<3"]))
    assert module.check() == 0


def test_stanza_uses_the_normalised_pypi_name(monkeypatch) -> None:
    """Homebrew's audit rejects `resource "pydantic_core"`: PyPI registers the
    underscore spelling, but brew wants the PEP 503 name `pydantic-core`."""
    import io
    import json

    module = _load()
    payload = {
        "info": {"name": "Pydantic_Core"},
        "urls": [
            {
                "packagetype": "sdist",
                "url": "https://files.example/pydantic_core-2.0.tar.gz",
                "digests": {"sha256": "ab" * 32},
            }
        ],
    }

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *a, **k: _Response(json.dumps(payload).encode()),
    )
    block = module.stanza("pydantic_core", "2.0")
    assert block is not None
    assert block.startswith('  resource "pydantic-core" do\n')

"""gen-icons.py builds the Lucide sprite and catches drift in --check mode.

Purpose    : Prove the sprite generator emits one <symbol> per pinned subset
             entry, carries each entry's group onto the symbol itself, and
             reports a stale committed file instead of silently rewriting it.
Inputs     : packaging/data/lucide-subset.json and packaging/vendor/lucide/
             as they exist in the checkout.
Outputs    : Assertions only. OUTPUT is redirected into tmp_path, so a test
             run never regenerates the tracked web/icons.svg -- the same
             rule test_docs_scripts.py follows for the wiki generators.
Constraints: gen-icons.py lives outside the findplus package with a
             hyphenated filename, so it is loaded via importlib.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "packaging" / "scripts"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_icons", SCRIPTS_DIR / "gen-icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _subset(module: ModuleType) -> list[dict[str, str]]:
    return json.loads(module.SUBSET.read_text(encoding="utf-8"))


def _write_into(module: ModuleType, tmp_path: Path, monkeypatch) -> Path:
    out = tmp_path / "icons.svg"
    monkeypatch.setattr(module, "OUTPUT", out)
    assert module.main(check=False) == 0
    return out


def test_gen_icons_produces_49_symbols(tmp_path, monkeypatch) -> None:
    """48 badge icons plus UAT2 U26's `bell` (the phone-tier tab bar)."""
    module = _load()
    text = _write_into(module, tmp_path, monkeypatch).read_text(encoding="utf-8")
    assert text.startswith('<svg id="fp-icon-sprite"')
    assert 'id="fp-icon-sprite"' in text
    assert text.count('<symbol id="lucide-') == 49


def test_gen_icons_check_mode_detects_drift(tmp_path, monkeypatch) -> None:
    module = _load()
    out = _write_into(module, tmp_path, monkeypatch)
    assert module.main(check=True) == 0
    out.write_text(out.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert module.main(check=True) == 1


def test_every_subset_id_has_a_vendored_svg() -> None:
    module = _load()
    entries = _subset(module)
    assert len(entries) == 49
    for entry in entries:
        name = entry["id"].split(":", 1)[1]
        assert (module.VENDOR_DIR / f"{name}.svg").exists(), name


def test_every_symbol_carries_its_subset_group(tmp_path, monkeypatch) -> None:
    module = _load()
    text = _write_into(module, tmp_path, monkeypatch).read_text(encoding="utf-8")
    assert text.count('data-group="') == 49
    for entry in _subset(module):
        name = entry["id"].split(":", 1)[1]
        assert f'id="lucide-{name}" data-group="{entry["group"]}"' in text

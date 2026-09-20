"""Guards on the release workflow that no test could reach before.

E1 packaging round 2 F2 and F3. Neither path had ever been exercised: the
signed path needs an Apple certificate, and the tap path needs a tag. These
tests read the workflow and the generator as text, which is enough to catch
both regressions:

  F2 - gen-formula.sh had no GitHub-release branch, so every tag overwrote the
       working formula url with a pythonhosted placeholder for a package that
       was never uploaded, and the tap PR opened against a DRAFT release whose
       assets are not publicly downloadable.
  F3 - the p12 was imported with no keychain and no partition list, so every
       codesign would have failed with errSecInternalComponent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
GEN_FORMULA = ROOT / "packaging" / "scripts" / "gen-formula.sh"


def _sign_step() -> dict:
    yaml = pytest.importorskip("yaml")
    jobs = yaml.safe_load(RELEASE.read_text())["jobs"]
    for step in jobs["build-dmg"]["steps"]:
        if step.get("name") == "Sign sidecar":
            return step
    raise AssertionError("the Sign sidecar step is gone from release.yml")


def test_the_signing_step_sets_a_key_partition_list() -> None:
    run = _sign_step()["run"]
    assert "security create-keychain" in run
    assert "security unlock-keychain" in run
    assert "set-key-partition-list" in run, (
        "without a partition list every codesign fails non-interactively with "
        "errSecInternalComponent"
    )
    assert "apple-tool:,apple:,codesign:" in run


def test_the_decoded_certificate_is_always_removed() -> None:
    run = _sign_step()["run"]
    assert "trap 'rm -f" in run, "the decoded p12 must not outlive the step"
    assert "/tmp/cert.p12" not in run, "key material belongs in RUNNER_TEMP, not /tmp"


def test_the_formula_generator_has_a_github_release_branch() -> None:
    script = GEN_FORMULA.read_text()
    assert "releases/download/v$VERSION" in script, (
        "PyPI publish is deferred, so the fetchable sdist is the GitHub release asset"
    )
    assert "packages/source/f/findplus" not in script, (
        "the legacy pythonhosted placeholder points at a package nobody uploaded"
    )


def test_the_tap_pr_is_gated_on_a_published_release() -> None:
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(RELEASE.read_text())["jobs"]["update-tap"]["steps"]
    assert any("isDraft" in str(s.get("run", "")) for s in steps), (
        "github-release creates a draft, whose assets are not publicly downloadable"
    )
    gated = [s for s in steps if s.get("if") == "steps.release.outputs.draft != 'true'"]
    assert len(gated) >= 4, "every step that writes or pushes the formula must be gated"

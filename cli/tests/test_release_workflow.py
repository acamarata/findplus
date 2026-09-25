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
    jobs = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]
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
    script = GEN_FORMULA.read_text(encoding="utf-8")
    assert "releases/download/v$VERSION" in script, (
        "PyPI publish is deferred, so the fetchable sdist is the GitHub release asset"
    )
    assert "packages/source/f/findplus" not in script, (
        "the legacy pythonhosted placeholder points at a package nobody uploaded"
    )


def test_the_tap_pr_is_gated_on_a_published_release() -> None:
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]["update-tap"]["steps"]
    assert any("isDraft" in str(s.get("run", "")) for s in steps), (
        "github-release creates a draft, whose assets are not publicly downloadable"
    )
    gated = [s for s in steps if s.get("if") == "steps.release.outputs.draft != 'true'"]
    assert len(gated) >= 4, "every step that writes or pushes the formula must be gated"


def test_the_tap_formula_hashes_the_released_sdist() -> None:
    """v1.1.0: the release was cut locally, github-release kept its assets, and
    the tap job hashed this run's own python-dist build instead, a different
    tarball whose sha256 would have broken every `brew install`."""
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]["update-tap"]["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    assert any("gh release download" in r and "tar.gz" in r for r in runs)
    assert not any(s.get("with", {}).get("name") == "python-dist" for s in steps), (
        "the tap must hash the sdist attached to the release, not a fresh CI build"
    )


def test_no_script_writes_key_material_to_a_fixed_path() -> None:
    """E1 confirmation pass F1: the signing key must not outlive its use.

    release-local.sh decoded APPLE_API_KEY_P8_BASE64 to a fixed, world-readable
    /tmp/findplus-api-key.p8 with no cleanup, leaving the Apple signing key
    readable by every local user for good -- while embed-widget.sh, the script
    that actually uses it, already decodes it to a mktemp file under a
    `trap ... EXIT`. The second decode was dead weight as well as a leak.
    """
    for script in sorted((ROOT / "packaging" / "scripts").glob("*.sh")):
        code = "\n".join(
            line
            for line in script.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        if "base64 -d" not in code:
            continue
        assert "/tmp/" not in code, f"{script.name} writes decoded material to a fixed /tmp path"
        assert "mktemp" in code and "trap" in code, (
            f"{script.name} decodes a secret without a mktemp file and a cleanup trap"
        )


def test_the_bundle_is_checked_for_dotdirs_before_sign_off() -> None:
    """E1 packaging round 3 F2: the published dmg shipped web/.claude/ inside it.

    The specs are fixed and unit-tested, but a spec test reads the spec, not
    the bundle that was actually produced, and no release step had ever looked
    inside one.
    """
    embed = (ROOT / "packaging" / "scripts" / "embed-widget.sh").read_text(encoding="utf-8")
    i = embed.index("-path '*/.claude/*'")
    guard = embed[i : embed.index("codesign --verify", i)]
    assert "exit 1" in guard, "finding .claude/ must fail the release, not just print"


def test_ci_lints_every_shell_script() -> None:
    """E1 packaging round 3 F3: the gate covered install.sh only, 1 of 15."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "shellcheck install.sh packaging/scripts/*.sh" in ci


def test_one_supported_python_window() -> None:
    """E1 packaging round 3 F4: it was stated three different ways."""
    pyproject = (ROOT / "cli" / "pyproject.toml").read_text(encoding="utf-8")
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.12,<3.15"' in pyproject
    assert "(3, 12) <= sys.version_info < (3, 15)" in install
    assert "Python 3.12, 3.13 or 3.14" in readme
    assert "Python 3.12 or newer" not in readme

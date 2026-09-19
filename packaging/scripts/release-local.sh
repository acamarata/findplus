#!/usr/bin/env bash
# release-local.sh: owner-only; requires TWINE_USERNAME and
# TWINE_PASSWORD_TESTPYPI env vars
#
# Purpose    : Local driver for a full findplus release: build, twine check,
#              TestPyPI, PyPI (with confirmation), then the macOS steps
#              (Homebrew formula generation now; dmg sign/notarize/upload and
#              tap update are stubbed until E13/E16 land).
# Inputs     : $1 = version, X.Y.Z, must match cli/pyproject.toml.
# Outputs    : dist/ artifacts, a TestPyPI upload, an optional PyPI upload,
#              packaging/homebrew/findplus.rb (via gen_formula).
# Constraints: step_pypi's confirmation prompt is not bypassable by env var;
#              SKIP_MACOS=1 or a non-Darwin uname skips the macOS block.
set -euo pipefail

echo "release-local.sh: owner-only; requires TWINE_USERNAME and TWINE_PASSWORD_TESTPYPI env vars"

if [ $# -ne 1 ]; then
  echo "Usage: release-local.sh <version>  e.g. 1.0.0"
  exit 2
fi

VERSION="$1"

PYPROJECT_VER=$(grep -m1 'version = ' cli/pyproject.toml)
if ! echo "$PYPROJECT_VER" | grep -q "\"$VERSION\""; then
  echo "Version mismatch: cli/pyproject.toml has $PYPROJECT_VER; expected $VERSION. Run bump-version.sh first."
  exit 1
fi

step_build() {
  echo "==> build"
  rm -rf dist
  python -m build --outdir dist cli
}

step_twine_check() {
  echo "==> twine check"
  twine check dist/*
}

step_testpypi() {
  echo "==> upload to TestPyPI"
  twine upload --repository testpypi \
    --username "${TWINE_USERNAME:-__token__}" \
    --password "${TWINE_PASSWORD_TESTPYPI}" dist/*
}

step_pypi() {
  echo "==> upload to PyPI (REQUIRES OWNER CONFIRMATION)"
  printf "Upload findplus==%s to PyPI? [y/N] " "$VERSION"
  read -r ans
  [ "$ans" = y ] || [ "$ans" = Y ] || {
    echo "Aborted."
    return 0
  }
  twine upload --repository pypi \
    --username "${TWINE_USERNAME:-__token__}" \
    --password "${TWINE_PASSWORD_PYPI}" dist/*
}

gen_formula() {
  packaging/scripts/gen-formula.sh dist/*.tar.gz
}

sign_dmg() { echo "sign_dmg: not yet implemented (E16-T5 / packaging/scripts/sign-sidecar.sh)"; }
notarize_dmg() { echo "notarize_dmg: not yet implemented (E16-T5)"; }
package_dmg() { echo "package_dmg: not yet implemented (E13-T6)"; }
upload_dmg() { echo "upload_dmg: not yet implemented (E13-T6)"; }
update_tap() { echo "update_tap: not yet implemented (E13-T6)"; }

main() {
  step_build
  step_twine_check
  step_testpypi
  step_pypi

  if [ "${SKIP_MACOS:-0}" != "1" ] && [ "$(uname)" = Darwin ]; then
    gen_formula
    package_dmg
    sign_dmg
    notarize_dmg
    upload_dmg
    update_tap
  else
    echo "Skipping macOS steps (SKIP_MACOS=1 or not on macOS)."
  fi

  echo "Release $VERSION complete."
}

main

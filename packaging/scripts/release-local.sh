#!/usr/bin/env bash
# release-local.sh: owner-only; requires TWINE_USERNAME and
# TWINE_PASSWORD_TESTPYPI env vars
#
# Purpose    : Local driver for a full findplus release: build, twine check,
#              TestPyPI, PyPI (with confirmation), then the macOS desktop
#              app build-and-sign sequence (specs/desktop-app.md § Build &
#              sign) and the Homebrew formula.
# Inputs     : $1 = version, X.Y.Z, must match cli/pyproject.toml.
# Outputs    : dist/ artifacts, a TestPyPI upload, an optional PyPI upload,
#              packaging/homebrew/findplus.rb, a signed (if APPLE_SIGNING_
#              IDENTITY is set) Find+.app and dmg under desktop/src-tauri/
#              target/aarch64-apple-darwin/release/bundle/.
# Constraints: step_pypi's confirmation prompt is not bypassable by env var;
#              SKIP_MACOS=1 or a non-Darwin uname skips the macOS block.
#              Only the cargo-tauri-build step runs from desktop/src-tauri
#              (Cargo.toml/tauri.conf.json live there); every other step,
#              including verification, runs from the repo root and refers
#              to build outputs via the explicit desktop/src-tauri/target/…
#              prefix.
set -euo pipefail

echo "release-local.sh: owner-only; requires TWINE_USERNAME and TWINE_PASSWORD_TESTPYPI env vars"

if [ $# -ne 1 ]; then
  echo "Usage: release-local.sh <version>  e.g. 1.0.0"
  exit 2
fi

VERSION="$1"
BUNDLE_DIR="desktop/src-tauri/target/aarch64-apple-darwin/release/bundle"

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

# ------------------------------------------------- macOS desktop app (E13-T6)
macos_step1_sidecar() {
  echo "==> PyInstaller sidecar"
  pyinstaller packaging/pyinstaller/findplus-daemon.spec
}

macos_step2_sign_sidecar() {
  echo "==> Sign sidecar"
  bash packaging/scripts/sign-sidecar.sh
}

macos_step3_widget() {
  echo "==> Widget build"
  xcodebuild -project desktop/widget/FindPlusWidget.xcodeproj \
    -scheme FindPlusWidget -configuration Release -arch arm64 build
}

macos_step4_tauri_build() {
  echo "==> cargo tauri build"
  ( cd desktop/src-tauri && cargo tauri build --target aarch64-apple-darwin )
}

macos_step5_embed_widget() {
  echo "==> Embed widget"
  bash packaging/scripts/embed-widget.sh
}

macos_step6_verify() {
  echo "==> Verify"
  local app="$BUNDLE_DIR/macos/Find+.app"
  local dmg
  dmg=$(find "$BUNDLE_DIR/dmg" -name 'Find+_*.dmg' 2>/dev/null | head -1 || true)
  spctl -a -vv --type install "$app"
  codesign --verify --deep --strict --verbose=2 "$app"
  if [ -n "$dmg" ]; then
    # verify-dmg.sh runs hdiutil verify AND enforces the 120 MB budget
    # (specs/desktop-app.md § Build & sign step 6); calling hdiutil directly
    # here would skip the size gate the CHANGELOG promises.
    bash packaging/scripts/verify-dmg.sh "$dmg"
  fi
  echo "release-local: PASS v$VERSION"
}

update_tap() { echo "update_tap: not yet implemented (E14-T1, after the main push)"; }

main() {
  step_build
  step_twine_check
  step_testpypi
  step_pypi

  if [ "${SKIP_MACOS:-0}" != "1" ] && [ "$(uname)" = Darwin ]; then
    gen_formula
    macos_step1_sidecar
    macos_step2_sign_sidecar
    macos_step3_widget
    macos_step4_tauri_build
    macos_step5_embed_widget
    macos_step6_verify
    update_tap
  else
    echo "Skipping macOS steps (SKIP_MACOS=1 or not on macOS)."
  fi

  echo "Release $VERSION complete."
}

main

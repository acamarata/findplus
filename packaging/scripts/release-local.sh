#!/usr/bin/env bash
# release-local.sh: reproduces .github/workflows/release.yml on the owner's Mac.
#
# Purpose    : Bump the version, build wheel/sdist, sign+notarise the
#              sidecar/app/widget, rebuild the dmg, then print the
#              upload/release commands. Never uploads to PyPI or creates a
#              GitHub release itself.
# Inputs     : $1 = version X.Y.Z. ~/.claude/vault.env, if present, supplies
#              APPLE_* secrets (this script's own venv, not system Python).
# Outputs    : dist/ (wheel+sdist), packaging/homebrew/findplus.rb, a signed
#              Find+.app and FindPlus-<ver>-aarch64.dmg (+.sha256) at root.
# Constraints: SKIP_MACOS=1 or non-Darwin skips the macOS block; cargo tauri
#              build runs from desktop/src-tauri, everything else from root.
set -euo pipefail

VERSION=${1:?Usage: release-local.sh <version>  e.g. 1.0.0}
if [ -f "$HOME/.claude/vault.env" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.claude/vault.env"
fi

PY="./.venv/bin/python"
TWINE="./.venv/bin/twine"
PYINSTALLER="./.venv/bin/pyinstaller"

PYPROJECT_VER=$(grep -m1 'version = ' cli/pyproject.toml | sed 's/version = "\(.*\)"/\1/')
if [ "$PYPROJECT_VER" != "$VERSION" ]; then
  echo "Bumping cli/pyproject.toml from $PYPROJECT_VER to $VERSION"
  FINDPLUS_YES=1 bash packaging/scripts/bump-version.sh "$VERSION"
fi

step_build() {
  echo "==> build wheel + sdist"
  rm -rf dist
  "$PY" -m build --outdir dist cli
  "$TWINE" check dist/*
}

gen_formula() {
  bash packaging/scripts/gen-formula.sh dist/*.tar.gz
}

# ------------------------------------------------- macOS desktop app (E13-T6)
macos_step1_sidecar() {
  echo "==> PyInstaller sidecar"
  "$PYINSTALLER" packaging/pyinstaller/findplus-daemon.spec
}

macos_step2_sign_sidecar() {
  echo "==> Sign sidecar"
  bash packaging/scripts/sign-sidecar.sh
}

macos_step3_widget() {
  echo "==> Widget build"
  xcodebuild -project desktop/widget/FindPlusWidget.xcodeproj \
    -scheme FindPlusWidgetExtension -configuration Release -arch arm64 build
}

macos_step4_tauri_build() {
  echo "==> cargo tauri build"
  ( cd desktop/src-tauri && cargo tauri build --target aarch64-apple-darwin )
}

macos_step5_embed_widget() {
  # embed-widget.sh reads APPLE_API_KEY_P8_BASE64 itself and decodes it to a
  # mktemp file under a `trap ... EXIT` (embed-widget.sh:107-110), so the key
  # never outlives the notarisation call. This function used to decode the same
  # secret a second time to a fixed, world-readable /tmp/findplus-api-key.p8
  # with no cleanup -- leaving the signing key readable by every local user for
  # good -- and export it under names embed-widget.sh does not read. Both the
  # decode and the exports were dead weight as well as a leak.
  echo "==> Embed widget, sign, notarise, rebuild dmg"
  bash packaging/scripts/embed-widget.sh
}

macos_step6_finish() {
  local dmg suffix=""
  dmg=$(find dist -maxdepth 1 -name 'FindPlus-*.dmg' 2>/dev/null | head -1 || true)
  [ -n "$dmg" ] || { echo "no dmg produced by embed-widget.sh" >&2; return 1; }
  [ -n "${APPLE_SIGNING_IDENTITY:-}" ] || suffix="-UNSIGNED"
  cp "$dmg" "FindPlus-${VERSION}-aarch64${suffix}.dmg"
  shasum -a 256 "FindPlus-${VERSION}-aarch64${suffix}.dmg" > "FindPlus-${VERSION}-aarch64${suffix}.dmg.sha256"
  [ -n "$suffix" ] || bash packaging/scripts/verify-dmg.sh "FindPlus-${VERSION}-aarch64.dmg"
}

bake_installer_version() {
  # install.sh is uploaded as a release asset, so its VERSION_PIN default must
  # be the version being released; without this the published one-liner keeps
  # installing whatever placeholder was committed.
  echo "==> bake $VERSION into install.sh"
  perl -pi -e "s/^VERSION_PIN=.*/VERSION_PIN=\"\\\${FINDPLUS_VERSION:-$VERSION}\"/" install.sh
  grep -n '^VERSION_PIN=' install.sh
}

print_instructions() {
  echo "Release $VERSION built locally. To finish:"
  echo "  $TWINE upload dist/*"
  echo "  gh release create v${VERSION} dist/*.whl dist/*.tar.gz install.sh FindPlus-${VERSION}-*.dmg FindPlus-${VERSION}-*.dmg.sha256 --draft"
}

main() {
  bake_installer_version
  step_build

  if [ "${SKIP_MACOS:-0}" != "1" ] && [ "$(uname)" = Darwin ]; then
    gen_formula
    macos_step1_sidecar
    macos_step2_sign_sidecar
    macos_step3_widget
    macos_step4_tauri_build
    macos_step5_embed_widget
    macos_step6_finish
  else
    echo "Skipping macOS steps (SKIP_MACOS=1 or not on macOS)."
  fi

  print_instructions
}

main

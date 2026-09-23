#!/usr/bin/env bash
# release-local.sh: reproduces .github/workflows/release.yml on the owner's Mac.
#
# Purpose    : Bump the version, build wheel/sdist, sign+notarise the
#              sidecar/app/widget, rebuild the dmg, then print the
#              upload/release commands. Never uploads to PyPI or creates a
#              GitHub release itself.
# Inputs     : $1 = version X.Y.Z. $ARCH (default aarch64; x86_64 requires a
#              native Intel shell -- see the Rosetta guard below, this script
#              never cross-compiles Python). ~/.claude/vault.env, if present,
#              supplies APPLE_* secrets (this script's own venv, not system
#              Python).
# Outputs    : dist/ (wheel+sdist), packaging/homebrew/findplus.rb, a signed
#              Find+.app and FindPlus-<ver>-<arch>.dmg (+.sha256) at root.
# Constraints: SKIP_MACOS=1 or non-Darwin skips the macOS block; cargo tauri
#              build runs from desktop/src-tauri, everything else from root.
set -euo pipefail

VERSION=${1:?Usage: release-local.sh <version>  e.g. 1.0.0}
if [ -f "$HOME/.claude/vault.env" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.claude/vault.env"
fi

# --- ARCH ---------------------------------------------------------------
# aarch64 (Apple Silicon) is the default and the only arch this script has
# ever built locally. x86_64 (Intel) is accepted but this machine builds it
# natively or not at all -- PyInstaller bundles whatever Python it runs
# under, so an arm64 shell can only ever produce an arm64 sidecar no matter
# which spec file is pointed at.
ARCH="${ARCH:-aarch64}"
case "$ARCH" in
  aarch64 | arm64) ARCH=aarch64 ;;
  x86_64) ARCH=x86_64 ;;
  *)
    echo "release-local.sh: unsupported ARCH '$ARCH' (use aarch64 or x86_64)" >&2
    exit 1
    ;;
esac

if [ "$ARCH" = x86_64 ] && [ "$(uname -m)" != x86_64 ]; then
  cat >&2 <<'EOF'
release-local.sh: ARCH=x86_64 requested but this shell reports arm64
(`uname -m`). The Intel sidecar/app needs a native x86_64 toolchain running
under Rosetta; this script does not cross-compile Python and will not
attempt an Intel build from an arm64 shell. To build locally:
  1. softwareupdate --install-rosetta   (if not already installed)
  2. arch -x86_64 zsh                    (re-launch this shell under Rosetta)
  3. Build (or rebuild) ./.venv there with an x86_64 Python, then:
       ARCH=x86_64 bash packaging/scripts/release-local.sh <version>
Until then, use the CI release workflow's x86_64 matrix leg instead
(.github/workflows/release.yml build-dmg job, runs-on: macos-15-intel).
EOF
  exit 1
fi

if [ "$ARCH" = x86_64 ]; then
  PI_SPEC="packaging/pyinstaller/findplus-daemon-x86_64.spec"
  TAURI_TARGET="x86_64-apple-darwin"
  WIDGET_ARCH="x86_64"
else
  PI_SPEC="packaging/pyinstaller/findplus-daemon.spec"
  TAURI_TARGET="aarch64-apple-darwin"
  WIDGET_ARCH="arm64"
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
  echo "==> PyInstaller sidecar ($ARCH)"
  "$PYINSTALLER" "$PI_SPEC"
}

macos_step2_sign_sidecar() {
  echo "==> Sign sidecar"
  bash packaging/scripts/sign-sidecar.sh
}

macos_step3_widget() {
  echo "==> Widget build ($WIDGET_ARCH)"
  # Build where embed-widget.sh looks for the appex, and never reuse a stale one.
  # A project-relative path also avoids a global DerivedData on an unmounted volume.
  rm -rf desktop/widget/build
  xcodebuild -project desktop/widget/FindPlusWidget.xcodeproj \
    -scheme FindPlusWidgetExtension -configuration Release -arch "$WIDGET_ARCH" build \
    -derivedDataPath desktop/widget/build ONLY_ACTIVE_ARCH=NO CODE_SIGNING_ALLOWED=NO
}

macos_step4_tauri_build() {
  echo "==> cargo tauri build ($TAURI_TARGET)"
  ( cd desktop/src-tauri && cargo tauri build --target "$TAURI_TARGET" )
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
  APP_PATH="desktop/src-tauri/target/$TAURI_TARGET/release/bundle/macos/Find+.app" \
    ARCH_SUFFIX="$ARCH" \
    bash packaging/scripts/embed-widget.sh
}

macos_step6_finish() {
  local dmg suffix=""
  dmg=$(find dist -maxdepth 1 -name 'FindPlus-*.dmg' 2>/dev/null | head -1 || true)
  [ -n "$dmg" ] || { echo "no dmg produced by embed-widget.sh" >&2; return 1; }
  [ -n "${APPLE_SIGNING_IDENTITY:-}" ] || suffix="-UNSIGNED"
  cp "$dmg" "FindPlus-${VERSION}-${ARCH}${suffix}.dmg"
  shasum -a 256 "FindPlus-${VERSION}-${ARCH}${suffix}.dmg" > "FindPlus-${VERSION}-${ARCH}${suffix}.dmg.sha256"
  [ -n "$suffix" ] || bash packaging/scripts/verify-dmg.sh "FindPlus-${VERSION}-${ARCH}.dmg"
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

#!/usr/bin/env bash
# sign-sidecar.sh — sign every Mach-O in the PyInstaller onedir, innermost
# first, then sign the directory bundle itself.
#
# Purpose    : Pre-sign the sidecar before `cargo tauri build` — Gatekeeper
#              rejects the outer .app if any embedded Mach-O is unsigned,
#              even when the outer bundle itself is properly signed.
# Inputs     : $1 = onedir path (default: desktop/src-tauri/resources/
#              findplus-daemon, where the PyInstaller spec puts it so the Tauri
#              bundler ships it as a resource). APPLE_SIGNING_IDENTITY env var.
# Outputs    : Signed binaries in place; "sign-sidecar: PASS" on success.
# Constraints: No identity -> skip cleanly (exit 0), never fail the build.
#              Frameworks are signed as versioned bundles, never as the bare
#              Mach-O inside them, and the onedir directory is left unsigned.
set -euo pipefail

IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
SIDECAR_DIR="${1:-desktop/src-tauri/resources/findplus-daemon}"

if [ -z "$IDENTITY" ]; then
  echo "No APPLE_SIGNING_IDENTITY; skipping signing"
  exit 0
fi

if [ ! -d "$SIDECAR_DIR" ]; then
  echo "FAIL: sidecar directory not found: $SIDECAR_DIR" >&2
  exit 1
fi

sign_one() {
  codesign --force --options runtime --timestamp \
    --entitlements packaging/entitlements.plist \
    --sign "$IDENTITY" "$1"
}

# Frameworks first, and as versioned bundles. Signing the Mach-O inside a
# framework directly leaves a signature the notary service rejects with "the
# signature of the binary is invalid", because a framework has to be sealed at
# its version directory. PyInstaller ships CPython as Python.framework, and
# _internal/Python is a symlink into it, so the plain-file pass below must skip
# everything under a .framework.
find "$SIDECAR_DIR" -type d -name '*.framework' | while read -r fw; do
  for version in "$fw"/Versions/*; do
    case "$version" in
      */Current) continue ;;
    esac
    [ -d "$version" ] || continue
    echo "Signing framework version $version"
    sign_one "$version"
  done
  echo "Signing framework $fw"
  sign_one "$fw"
done

# Then every other Mach-O, innermost first: sort candidate paths by string
# length (descending) so the deepest paths are signed before their parents.
find "$SIDECAR_DIR" -type f | grep -v '\.framework/' | while read -r f; do
  if file "$f" | grep -q 'Mach-O'; then
    echo "${#f} $f"
  fi
done | sort -rn | awk '{print $2}' | while read -r binary; do
  echo "Signing $binary"
  sign_one "$binary"
done

# The onedir itself is a plain directory, not a bundle. Signing it produced a
# _CodeSignature seal that went stale the moment anything under it was
# re-signed, so it is deliberately not signed here; the outer Find+.app seals
# this tree through its own CodeResources.

find "$SIDECAR_DIR" -type f | grep -v '\.framework/' | while read -r f; do
  if file "$f" | grep -q 'Mach-O'; then
    codesign --verify --strict "$f" || exit 1
  fi
done
codesign --verify --strict "$SIDECAR_DIR/_internal/Python.framework"
echo "sign-sidecar: PASS"

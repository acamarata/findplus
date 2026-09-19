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

# Sign every Mach-O innermost first: sort candidate paths by string length
# (descending) so the deepest paths are signed before their parents.
find "$SIDECAR_DIR" -type f | while read -r f; do
  if file "$f" | grep -q 'Mach-O'; then
    echo "${#f} $f"
  fi
done | sort -rn | awk '{print $2}' | while read -r binary; do
  echo "Signing $binary"
  codesign --force --options runtime --timestamp \
    --entitlements packaging/entitlements.plist \
    --sign "$IDENTITY" "$binary"
done

codesign --force --options runtime --timestamp \
  --entitlements packaging/entitlements.plist \
  --sign "$IDENTITY" "$SIDECAR_DIR"

codesign --verify --deep --strict "$SIDECAR_DIR"
echo "sign-sidecar: PASS"

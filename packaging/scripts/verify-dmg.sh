#!/usr/bin/env bash
# verify-dmg.sh — checksum a built dmg and enforce the 120 MB size budget.
#
# Purpose    : Post-build release gate: catch dependency bloat before the
#              dmg ships (specs/desktop-app.md § Build & sign step 6).
# Inputs     : $1 = path to the built Find+ dmg.
# Outputs    : "verify-dmg: PASS (<n> MB)" on success; exit 1 over budget.
# Constraints: macOS only (hdiutil, BSD `stat -f%z`); CI's dmg job runs on
#              macos-latest (specs/packaging-and-release.md § CI jobs).
set -euo pipefail

DMG="${1:?Usage: verify-dmg.sh path/to/FindPlus.dmg}"

echo "==> hdiutil verify"
hdiutil verify "$DMG"

SIZE=$(stat -f%z "$DMG")
SIZE_MB=$((SIZE / 1048576))
echo "DMG size: ${SIZE_MB} MB"

if [ "$SIZE_MB" -gt 120 ]; then
  echo "FAIL: DMG exceeds 120 MB budget (${SIZE_MB} MB)" >&2
  exit 1
fi

echo "verify-dmg: PASS (${SIZE_MB} MB)"

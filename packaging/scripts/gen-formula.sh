#!/usr/bin/env bash
# gen-formula.sh — resolve packaging/homebrew/findplus.rb.tmpl into a real
# Homebrew formula from a built sdist.
#
# Purpose    : Replace __URL__, __SHA256__ and __RESOURCES__ placeholders in
#              the template using data derived from a local sdist tarball.
# Inputs     : $1 = path to a findplus-VERSION.tar.gz sdist.
# Outputs    : packaging/homebrew/findplus.rb (gitignored, regenerated).
# Constraints: __RESOURCES__ requires Homebrew (macOS); on Linux/CI it is
#              left in place with a warning to stderr.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: gen-formula.sh <sdist-tarball>" >&2
  exit 2
fi

SDIST="$1"
TMPL="packaging/homebrew/findplus.rb.tmpl"
OUT="packaging/homebrew/findplus.rb"

HASH=$(shasum -a 256 "$SDIST" | awk '{print $1}')
# forge choice: real URL is verified by the owner on first upload.
URL="https://files.pythonhosted.org/packages/source/f/findplus/$(basename "$SDIST")"

TMP="$(mktemp)"
cp "$TMPL" "$TMP"
# Substitute via %ENV (not string interpolation) so URL/HASH punctuation
# (":", "/", ".") is never treated as perl regex or replacement syntax.
FP_URL="$URL" FP_SHA256="$HASH" perl -pi -e \
  's/__URL__/$ENV{FP_URL}/; s/__SHA256__/$ENV{FP_SHA256}/' "$TMP"

if command -v brew >/dev/null 2>&1; then
  RESOURCES="$(brew update-python-resources --print-only "$(pwd)/$SDIST" 2>/dev/null || true)"
  if [ -n "$RESOURCES" ]; then
    awk -v resources="$RESOURCES" '/^__RESOURCES__$/{print resources; next} {print}' "$TMP" >"$TMP.new"
    mv "$TMP.new" "$TMP"
  else
    echo "gen-formula.sh: brew update-python-resources produced no output; leaving __RESOURCES__ token" >&2
  fi
else
  echo "gen-formula.sh: brew not available; leaving __RESOURCES__ token" >&2
fi

mv "$TMP" "$OUT"
echo "Formula written to packaging/homebrew/findplus.rb"

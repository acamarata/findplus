#!/usr/bin/env bash
# gen-formula.sh — resolve packaging/homebrew/findplus.rb.tmpl into a real
# Homebrew formula from a built sdist.
#
# Purpose    : Replace __URL__, __SHA256__ and __RESOURCES__ in the template
#              with data derived from a local sdist tarball.
# Inputs     : $1 = path to a findplus-VERSION.tar.gz sdist.
# Outputs    : packaging/homebrew/findplus.rb (gitignored, regenerated).
# Constraints: `brew update-python-resources` takes a FORMULA, not a tarball,
#              so the formula is written first and updated in place. If brew
#              cannot resolve it (offline, or the url is not on PyPI yet),
#              gen-resources.py fills the block from pip's own resolution of
#              the sdist. __RESOURCES__ never survives: an
#              unresolved token is a hard failure.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: gen-formula.sh <sdist-tarball>" >&2
  exit 2
fi

SDIST="$1"
TMPL="packaging/homebrew/findplus.rb.tmpl"
OUT="packaging/homebrew/findplus.rb"
HELPER="packaging/scripts/gen-resources.py"

HASH=$(shasum -a 256 "$SDIST" | awk '{print $1}')

# Prefer the exact sdist URL PyPI publishes (a hashed /packages/<a>/<b>/… path).
# Homebrew's FormulaAudit/PyPiUrls cop rejects the legacy /packages/source/f/…
# spelling, so that one is only a placeholder for a version not yet uploaded.
VERSION=$(basename "$SDIST" .tar.gz)
VERSION=${VERSION#findplus-}
URL=$(python3 -c 'import json,sys,urllib.request
try:
    d = json.load(urllib.request.urlopen("https://pypi.org/pypi/findplus/json", timeout=20))
    print(next(f["url"] for f in d["releases"].get(sys.argv[1], []) if f["packagetype"] == "sdist"))
except Exception:
    pass' "$VERSION" 2> /dev/null || true)

PLACEHOLDER_URL=false
if [ -z "$URL" ]; then
  PLACEHOLDER_URL=true
  URL="https://files.pythonhosted.org/packages/source/f/findplus/$(basename "$SDIST")"
  echo "gen-formula.sh: findplus $VERSION is not on PyPI yet; using the placeholder" >&2
  echo "gen-formula.sh: url. brew style reports FormulaAudit/PyPiUrls until it is." >&2
fi

# --- WRITE_FORMULA ------------------------------------------------------------
# Substitute via %ENV (not string interpolation) so URL/HASH punctuation
# (":", "/", ".") is never treated as perl regex or replacement syntax.
cp "$TMPL" "$OUT"
FP_URL="$URL" FP_SHA256="$HASH" perl -pi -e \
  's/__URL__/$ENV{FP_URL}/; s/__SHA256__/$ENV{FP_SHA256}/' "$OUT"

# --- RESOURCES_VIA_BREW -------------------------------------------------------
# brew wants the formula path and rewrites the resource blocks in place. It
# downloads the url to read the dependency tree, so it only works once the
# sdist is actually published.
if command -v brew > /dev/null 2>&1; then
  brew update-python-resources --ignore-non-pypi-packages "$PWD/$OUT" > /dev/null 2>&1 ||
    echo "gen-formula.sh: brew update-python-resources failed; using the local fallback" >&2
fi

# --- RESOURCES_VIA_SDIST ------------------------------------------------------
if grep -q '^__RESOURCES__$' "$OUT"; then
  echo "gen-formula.sh: filling resources with pip's resolver (full transitive closure)" >&2
  RES_FILE=$(mktemp)
  trap 'rm -f "$RES_FILE"' EXIT
  python3 "$HELPER" "$SDIST" > "$RES_FILE"
  # getline, not -v: BSD awk rejects a newline inside a -v assignment.
  awk -v f="$RES_FILE" \
    '/^__RESOURCES__$/{while ((getline line < f) > 0) print line; next} {print}' \
    "$OUT" > "$OUT.new"
  mv "$OUT.new" "$OUT"
fi

# --- VERIFY -------------------------------------------------------------------
if grep -q '__RESOURCES__\|__URL__\|__SHA256__' "$OUT"; then
  echo "FAIL: unresolved placeholder left in $OUT" >&2
  exit 1
fi

ruby -c "$OUT" > /dev/null
if command -v brew > /dev/null 2>&1; then
  # brew style only applies the formula cop set inside a tap-shaped path;
  # a loose .rb also trips generic Ruby cops (Sorbet sigils, class docs).
  STYLE_DIR=$(mktemp -d)/homebrew-tap/Formula
  mkdir -p "$STYLE_DIR"
  cp "$OUT" "$STYLE_DIR/findplus.rb"
  if [ "$PLACEHOLDER_URL" = true ]; then
    # Only FormulaAudit/PyPiUrls can fire here, and only because the version is
    # not uploaded yet; re-run after `twine upload` for the strict check.
    brew style "$STYLE_DIR/findplus.rb" ||
      echo "gen-formula.sh: style offences above are the unpublished-url case" >&2
  else
    brew style "$STYLE_DIR/findplus.rb"
  fi
fi

echo "Formula written to $OUT"

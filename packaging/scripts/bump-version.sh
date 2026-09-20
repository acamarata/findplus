#!/usr/bin/env bash
# bump-version.sh: owner-only release tool
#
# Purpose    : Update the version string in cli/pyproject.toml and add/refresh
#              its matching CHANGELOG.md header, and install.sh's default
#              VERSION_PIN (the bytes the README's curl-pipe one-liner runs).
# Inputs     : $1 = new version, X.Y.Z. FINDPLUS_YES=1 skips the confirmation
#              prompt (same convention as install.sh), so the script can run
#              unattended; without it an interactive confirmation is required.
# Outputs    : cli/pyproject.toml, CHANGELOG.md, install.sh updated in place. The desktop
#              app picks the version up automatically: desktop/src-tauri/
#              build.rs writes its semver form into tauri.conf.json.
# Constraints: refuses on a dirty git working tree; never git-commits or tags
#              (release-local.sh does that); owner-run only, never invoked by CI.
set -euo pipefail

echo "bump-version.sh: owner-only release tool"

if [ $# -ne 1 ]; then
  echo "Usage: bump-version.sh <new-version>  e.g. 1.0.0"
  exit 2
fi

NEW_VER="$1"

if ! echo "$NEW_VER" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "bump-version.sh: version must be X.Y.Z"
  exit 2
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "bump-version.sh: working tree is dirty. Commit or stash changes first."
  exit 1
fi

OLD_VER=$(grep -m1 '^version = ' cli/pyproject.toml | sed 's/version = "\(.*\)"/\1/')

echo "Bumping $OLD_VER -> $NEW_VER in:  cli/pyproject.toml  CHANGELOG.md  install.sh"
if [ "${FINDPLUS_YES:-0}" = 1 ]; then
  echo "FINDPLUS_YES=1; continuing without a prompt."
else
  printf "Continue? [y/N] "
  read -r ans
  [ "$ans" = y ] || [ "$ans" = Y ] || {
    echo "Aborted."
    exit 1
  }
fi

sed -i.bak "s/^version = \"$OLD_VER\"/version = \"$NEW_VER\"/" cli/pyproject.toml && rm cli/pyproject.toml.bak

# install.sh's default pin is what the README's `curl ... | bash` one-liner
# actually installs. Only the release ASSET copy was ever sed-baked, so the
# bytes on main kept pinning 1.0.0.dev0 -- a version no index carries -- long
# after pyproject said 1.0.0. cli/tests/test_install_sh_version.py asserts the
# two agree, so forgetting this line fails the suite rather than the user.
sed -i.bak "s|^VERSION_PIN=.*|VERSION_PIN=\"\${FINDPLUS_VERSION:-$NEW_VER}\"|" install.sh && rm install.sh.bak

# Idempotent: E14-T9 may already have written the "## [<ver>]" header before
# this script runs (E15-T6); if so, only refresh the date. Keeps [Unreleased]
# at the top either way. BSD sed cannot emit a newline in a replacement, so
# the new-header case uses perl -0pi (whole-file, multiline match).
TODAY=$(date +%F)
if grep -q "^## \[$NEW_VER\]" CHANGELOG.md; then
  perl -pi -e "s/^## \[\Q$NEW_VER\E\].*/## [$NEW_VER] - $TODAY/" CHANGELOG.md
else
  perl -0pi -e "s/^## \[Unreleased\]\n/## [Unreleased]\n\n## [$NEW_VER] - $TODAY\n/m" CHANGELOG.md
fi

echo "Done. Review the changes with: git diff"

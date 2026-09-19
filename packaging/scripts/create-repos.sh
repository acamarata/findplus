#!/usr/bin/env bash
# create-repos.sh — create acamarata/findplus and acamarata/homebrew-tap,
# set topics and branch protection. Run after the first push (E14-T10).
set -euo pipefail

DRY_RUN=0
for a in "$@"; do
  [ "$a" = "--dry-run" ] && DRY_RUN=1
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ $*"
  else
    "$@"
  fi
}

# --- 1. findplus repo (already exists, empty, per standing-authorizations.md) ---
run gh repo create acamarata/findplus \
  --public \
  --description "Local location history, places and alerts for Google Find Hub and Apple Find My trackers" \
  --license GPL-3.0-or-later \
  --homepage "https://github.com/acamarata/findplus" || echo "gh repo create: findplus already exists, continuing"

# --- 2. topics -------------------------------------------------------------
run gh api repos/acamarata/findplus/topics \
  -X PUT -f "names[]=find-hub" -f "names[]=find-my" \
  -f "names[]=location-history" -f "names[]=geofence" \
  -f "names[]=telegram" -f "names[]=tauri" \
  -f "names[]=fastapi" -f "names[]=sqlite" -f "names[]=mcp"

# --- 3. branch protection on main -------------------------------------------
run gh api repos/acamarata/findplus/branches/main/protection \
  -X PUT \
  --input packaging/scripts/branch-protection.json

# --- 4. homebrew-tap repo ----------------------------------------------------
run gh repo create acamarata/homebrew-tap \
  --public \
  --description "Homebrew tap for acamarata packages" \
  --license MIT || echo "gh repo create: homebrew-tap already exists, continuing"

run echo "Done. Push with: cd /Volumes/UG/Sites/acamarata/findplus && git remote add origin https://github.com/acamarata/findplus.git && git push -u origin main"

#!/usr/bin/env bash
# pre-push-check.sh — gate every push with six invariant checks.
#
# Purpose    : Prevent shipping a repo with stale names, AI attribution,
#              secrets, or misplaced planning docs.
# Inputs     : none (run from the repo root).
# Outputs    : "pre-push-check: all checks passed" and exit 0, or a list of
#              FAIL lines and exit 1.
# Constraints: collects every failure before exiting, so a developer sees
#              all problems in one run.
set -euo pipefail

FAIL=0

# --- 1. Clean root -------------------------------------------------------
# Checks what will actually be pushed: tracked entries, plus untracked ones
# that are not gitignored (a real stray file). Gitignored dev directories
# (.venv, .claude, build/, dist/, ...) are skipped, not flagged.
ALLOWED=".git .gitignore .gitleaks.toml README.md LICENSE CHANGELOG.md cli web desktop packaging .github install.sh"
# shellcheck disable=SC2045  # repo-root entries only, no spaces/globs expected
for f in $(ls -A .); do
  echo "$ALLOWED" | grep -qw "$f" && continue
  git check-ignore -q "$f" && continue
  echo "FAIL: unexpected root entry: $f"; FAIL=1
done

# --- 2. Old name grep ------------------------------------------------------
# git grep only searches tracked content, so build output and .claude/ are
# never scanned; the check script and .github/docs/ (which document the
# naming rule itself) are excluded from matching their own rule text.
# web/app/state.js's one mention is the documented localStorage migration
# shim (P1-E10-W6-S1-T1) explaining the old `bt.*` key prefix it reads once.
if git grep -l -I -i 'bike-tracker\|bike_tracker' -- \
   ':!packaging/scripts/pre-push-check.sh' ':!.github/docs/**' ':!.claude/**' \
   ':!web/app/state.js' \
   2>/dev/null; then
  echo "FAIL: old name 'bike-tracker' found in source files"; FAIL=1
fi

# --- 3. Co-Authored-By ---------------------------------------------------
if git log --format='%B' HEAD~10..HEAD 2>/dev/null | grep -i 'Co-Authored-By'; then
  echo "FAIL: Co-Authored-By found in recent commits"; FAIL=1
fi

# --- 4. gitleaks -----------------------------------------------------------
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-banner --config .gitleaks.toml --exit-code 1 || { echo "FAIL: gitleaks found secrets"; FAIL=1; }
else
  echo "WARN: gitleaks not installed; skipping secrets scan"
fi

# --- 5. Planning docs location ------------------------------------------
for f in PROMPT.md CONTEXT.md PLAN.md; do
  [ "${SKIP_PLANNING_DOCS:-0}" = "1" ] && continue
  if [ -f "$f" ]; then
    echo "FAIL: $f must be under .github/docs/, not at repo root"; FAIL=1
  fi
done

# --- 6. No "Find My+" ------------------------------------------------------
# .github/docs/ and this script are excluded: they document the naming rule
# itself ("never write Find My+"), not an instance of using it.
if git grep -n -I 'Find My+' -- \
   ':!packaging/scripts/pre-push-check.sh' ':!.github/docs/**' ':!.claude/**' \
   2>/dev/null; then
  echo "FAIL: 'Find My+' found (use 'Apple Find My' or 'Find My')"; FAIL=1
fi

[ "${FAIL:-0}" -eq 0 ] && echo "pre-push-check: all checks passed" || exit 1

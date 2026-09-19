#!/usr/bin/env bash
# install-hook.sh — install pre-push-check.sh as a local git pre-push hook.
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
HOOK="$REPO_ROOT/.git/hooks/pre-push"
echo '#!/usr/bin/env bash' > "$HOOK"
# shellcheck disable=SC2016  # single-quoted deliberately: written verbatim, expanded when the hook runs
echo 'exec bash "$(git rev-parse --show-toplevel)/packaging/scripts/pre-push-check.sh"' >> "$HOOK"
chmod +x "$HOOK"
echo "Installed pre-push hook at $HOOK"

#!/usr/bin/env bash
# sidecar-smoke.sh — verify the PyInstaller onedir bundle from a clean HOME.
#
# Purpose    : Prove the bundled daemon actually starts, migrates its own
#              database, and answers /api/health, without touching the real
#              ~/.findplus or the network.
# Inputs     : none (resolves the built binary; falls back to dist/ if the
#              Tauri binaries/ copy has not run yet).
# Outputs    : exit 0 and "sidecar smoke: PASS" on success.
# Constraints: Uses port 18647 (not 8647) so it never collides with a running
#              daemon. --no-poller prevents any Google auth attempt.
set -euo pipefail

BINARY="desktop/src-tauri/resources/findplus-daemon/findplus-daemon"
if [ ! -x "$BINARY" ]; then
  BINARY="dist/findplus-daemon/findplus-daemon"
fi
if [ ! -x "$BINARY" ]; then
  echo "FAIL: no findplus-daemon binary found (build the PyInstaller spec first)" >&2
  exit 1
fi

TMPDIR=$(mktemp -d)
export HOME="$TMPDIR"
export FINDPLUS_STATE_DIR="$TMPDIR/.findplus"
SIDECAR_PID=""
# Kill the server on every exit path, not just the happy one: an orphaned
# child keeps the script's stdout pipe open and the caller hangs for ever.
cleanup() {
  [ -n "$SIDECAR_PID" ] && kill "$SIDECAR_PID" 2> /dev/null
  wait "$SIDECAR_PID" 2> /dev/null
  rm -rf "$TMPDIR"
  return 0
}
trap cleanup EXIT

"$BINARY" --version

"$BINARY" serve --no-poller --port 18647 --foreground &
SIDECAR_PID=$!

HEALTHY=0
for _ in $(seq 1 20); do
  if curl -sf http://127.0.0.1:18647/api/health > /dev/null; then
    HEALTHY=1
    break
  fi
  sleep 1
done

if [ "$HEALTHY" -ne 1 ]; then
  echo "FAIL: health timeout" >&2
  exit 1
fi

"$BINARY" db upgrade

# v1.1.1 shipped a daemon whose Google sign-in helper crashed (no
# multiprocessing.freeze_support) and which lacked the Apple Find My library.
# selfcheck starts a real spawn child and imports findmy inside the bundle.
"$BINARY" selfcheck
if curl -sf http://127.0.0.1:18647/api/auth/status | grep -q apple_extra; then
  echo "FAIL: the bundled daemon reports needs apple_extra" >&2
  exit 1
fi

# doctor is advisory here: in a throwaway HOME it correctly reports "not
# authenticated", "service not installed" and exits non-zero. The smoke test
# only needs it to RUN inside the frozen bundle, so the exit code is ignored.
"$BINARY" doctor || true

echo "sidecar smoke: PASS"

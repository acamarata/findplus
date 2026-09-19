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

BINARY="desktop/src-tauri/binaries/findplus-daemon-aarch64-apple-darwin/findplus-daemon"
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
cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

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
  kill "$SIDECAR_PID" 2> /dev/null || true
  echo "FAIL: health timeout" >&2
  exit 1
fi

"$BINARY" db upgrade
"$BINARY" doctor

kill "$SIDECAR_PID"
wait "$SIDECAR_PID" 2> /dev/null || true

echo "sidecar smoke: PASS"

#!/usr/bin/env bash
# stage-sidecar-stub.sh — placeholder sidecar for the desktop lint/test CI job.
#
# Purpose    : tauri.conf.json's bundle.resources glob
#              ("resources/findplus-daemon/**/*") is validated by
#              tauri_build::build() on every `cargo build`/`cargo clippy`, but
#              desktop/src-tauri/resources/ is gitignored (findplus-daemon.spec
#              populates it from a real PyInstaller build). The `desktop` CI
#              job only lints/tests the Rust side and never runs PyInstaller,
#              so on a clean checkout the glob matches nothing and the build
#              fails before clippy even starts. This script stages a minimal
#              fake onedir so the glob resolves; it is never signed, bundled,
#              or shipped — only the real findplus-daemon.spec output is.
# Inputs     : none. Run from the repo root.
# Outputs    : desktop/src-tauri/resources/findplus-daemon/findplus-daemon, an
#              executable no-op stub. Exits 0 immediately (idempotent) if a
#              real or previously-staged sidecar is already there.
# Constraints: Never overwrites an existing resources/findplus-daemon/ — a
#              real PyInstaller build (release-local.sh, release.yml) always
#              wins if it ran first. desktop/src-tauri/binaries/findplus-daemon-*
#              (the externalBin launchers) are committed files, not staged here.
set -euo pipefail

DEST="desktop/src-tauri/resources/findplus-daemon"

if [ -e "$DEST" ]; then
  echo "stage-sidecar-stub: $DEST already exists, leaving it alone"
  exit 0
fi

mkdir -p "$DEST"
cat > "$DEST/findplus-daemon" <<'EOF'
#!/bin/sh
# Stub sidecar staged by packaging/scripts/stage-sidecar-stub.sh for CI lint
# and test only. Never bundled: a real build replaces this whole directory.
exit 0
EOF
chmod +x "$DEST/findplus-daemon"

echo "stage-sidecar-stub: staged placeholder at $DEST"

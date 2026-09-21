#!/usr/bin/env bash
# rehearse-first-run.sh — drive the real #/setup wizard through a fixture stub.
#
# Purpose    : Prove a first-time user reaches a working dashboard through
#              every step of the onboarding wizard, screenshotted at two
#              widths, with the labeled device and group actually saved.
# Inputs     : none.
# Outputs    : 16 PNGs + MANIFEST.txt under .github/docs/screenshots/setup/,
#              ending in REHEARSAL-FIRST-RUN-PASS.
# Constraints: throwaway HOME under /tmp/fp-first-run.*, never port 8647,
#              never the real ~/.findplus. The real daemon listens on 18648
#              (the browser never sees it); the fixture on 18647 is what
#              Playwright talks to. The only faked boundary is the Google
#              provider's network edge (LocationProvider protocol, same shape
#              cli/tests/api/test_devices_refresh.py's _Provider fakes) — every
#              other route (devices/groups/settings) is the real daemon.
# Reuse      : packaging/scripts/rehearse-fresh-machine.sh (isolation idioms).
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
CLEAN_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
WORK=""
DAEMON_PID=""
FIXTURE_PID=""

cleanup() {
  [ -n "$FIXTURE_PID" ] && kill "$FIXTURE_PID" 2>/dev/null || true
  [ -n "$DAEMON_PID" ] && kill "$DAEMON_PID" 2>/dev/null || true
  [ -n "$FIXTURE_PID" ] && wait "$FIXTURE_PID" 2>/dev/null || true
  [ -n "$DAEMON_PID" ] && wait "$DAEMON_PID" 2>/dev/null || true
  rm -rf "${WORK:?}"
}

WORK=$(mktemp -d /tmp/fp-first-run.XXXXXX)
trap cleanup EXIT
HOMEDIR="$WORK/home"
mkdir -p "$HOMEDIR"
unset VIRTUAL_ENV FINDPLUS_STATE_DIR

# A launcher, not `findplus serve` directly: it fakes ONLY the Google provider's
# network edge (same LocationProvider shape test_devices_refresh.py's _Provider
# fakes), then runs the real `serve` command unchanged. Never written into the
# repo; lives in the throwaway $WORK dir for this run only.
cat > "$WORK/daemon.py" <<'PYEOF'
import sys

import findplus.providers.base as _base
from findplus.providers.base import ProviderDevice


class _FixtureGoogle:
    name = "google-find-hub"
    display_name = "Google Find Hub"

    def is_available(self):
        return True, ""

    def is_authenticated(self):
        return True

    def describe_auth(self):
        return {"provider": "google-find-hub", "account": "test@example.invalid"}

    def list_devices(self):
        return [ProviderDevice(provider="google-find-hub", device_id="FIXTURE-TAG-1",
                                name="Fixture Tag", kind="tracker", raw={})]

    def locate(self, device_id, name):
        return []


_fake = _FixtureGoogle()
_base.available_providers = lambda: ["google-find-hub"]
_base.get_provider = lambda name: _fake

sys.argv = ["findplus", "serve", "--no-poller", "--port", "18648"]
from findplus.cli.main import main
main()
PYEOF

echo "== fake-provider daemon on 18648"
env -i HOME="$HOMEDIR" PATH="$CLEAN_PATH" TERM=dumb \
  "$REPO/.venv/bin/python" "$WORK/daemon.py" &
DAEMON_PID=$!
curl -fsS --retry 30 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:18648/api/health >/dev/null

echo "== auth fixture on 18647"
HOME="$HOMEDIR" "$REPO/.venv/bin/python" \
  "$REPO/packaging/scripts/fixture-auth-server.py" &
FIXTURE_PID=$!
curl -fsS --retry 10 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:18647/api/health >/dev/null

mkdir -p "$REPO/.github/docs/screenshots/setup"

echo "== driving the wizard"
BASE_URL="http://127.0.0.1:18647" OUT_DIR="$REPO/.github/docs/screenshots/setup" \
  "$REPO/.venv/bin/python" "$REPO/packaging/scripts/rehearse-first-run-drive.py"

kill "$FIXTURE_PID" "$DAEMON_PID"
wait "$FIXTURE_PID" "$DAEMON_PID" 2>/dev/null || true
FIXTURE_PID=""
DAEMON_PID=""

ls "$REPO/.github/docs/screenshots/setup/" > "$REPO/.github/docs/screenshots/setup/MANIFEST.txt"
echo REHEARSAL-FIRST-RUN-PASS

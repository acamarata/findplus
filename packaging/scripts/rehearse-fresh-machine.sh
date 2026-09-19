#!/usr/bin/env bash
# rehearse-fresh-machine.sh — install Find+ the way a new user would, twice.
#
# Purpose    : Prove that a machine holding nothing but Python 3.12 can install
#              Find+ from the wheel, run it, reinstall over itself and uninstall
#              cleanly, on macOS natively and in a python:3.12 container.
# Inputs     : $1 = macos | linux | all (default all).
# Outputs    : the asserts' output, ending in REHEARSAL-MACOS-PASS and
#              REHEARSAL-LINUX-PASS.
# Constraints: no privilege escalation, no new user account, no contact with the real
#              ~/.findplus or port 8647. A throwaway HOME under
#              /tmp/fp-rehearsal.* and env -i are the whole isolation story, and
#              the EXIT trap removes only that directory.
# Reuse      : install.sh:main and packaging/scripts/rehearsal-linux-inner.sh.
set -euo pipefail

MODE="${1:-all}"
REPO=$(cd "$(dirname "$0")/../.." && pwd)
CLEAN_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# Global, not local: the EXIT trap runs after the function frame is gone.
WORK=""

build_wheel() {
  git -C "$REPO" check-ignore -q dist || {
    echo "rehearse: dist is not gitignored; add /dist/ to .gitignore first" >&2
    exit 1
  }
  "$REPO/.venv/bin/python" -m build --wheel --outdir "$REPO/dist" "$REPO/cli" >/dev/null
  WHEEL=""
  for w in "$REPO"/dist/findplus-*-py3-none-any.whl; do
    [ -f "$w" ] && WHEEL="$w"
  done
  test -n "$WHEEL"
  echo "== wheel: $WHEEL"
}

macos_leg() {
  local HOMEDIR FPBIN VER PID
  WORK=$(mktemp -d /tmp/fp-rehearsal.XXXXXX)
  trap 'rm -rf "${WORK:?}"' EXIT
  HOMEDIR="$WORK/home"
  mkdir -p "$HOMEDIR"
  unset VIRTUAL_ENV FINDPLUS_STATE_DIR

  echo "== fresh install"
  env -i HOME="$HOMEDIR" PATH="$CLEAN_PATH" TERM=dumb FINDPLUS_YES=1 \
    FINDPLUS_WHEEL="$WHEEL" bash "$REPO/install.sh" 2>&1 | tee "$WORK/install.log"
  grep -q "Python:" "$WORK/install.log"
  grep -q "Venv:" "$WORK/install.log"
  grep -q "Symlink:" "$WORK/install.log"
  grep -q "Package:" "$WORK/install.log"

  FPBIN="$HOMEDIR/.local/bin/findplus"
  test -x "$FPBIN"
  VER=$(basename "$WHEEL" | cut -d- -f2)
  "$FPBIN" --version | grep -F "$VER"

  echo "== doctor"
  HOME="$HOMEDIR" "$FPBIN" doctor > "$WORK/doctor.log" 2>&1 || true
  grep -F "not signed-in" "$WORK/doctor.log"
  cat "$WORK/doctor.log"

  echo "== auth --help"
  HOME="$HOMEDIR" "$FPBIN" auth --help > /dev/null

  echo "== serve and probe"
  env -i HOME="$HOMEDIR" PATH="$CLEAN_PATH" TERM=dumb "$FPBIN" serve --no-poller \
    --port 18647 &
  PID=$!
  curl -fsS --retry 30 --retry-delay 1 --retry-connrefused \
    http://127.0.0.1:18647/api/health | grep -F '"app":"findplus"'
  kill "$PID"
  wait "$PID" 2>/dev/null || true

  echo "== state isolation"
  find "$HOMEDIR/.findplus" -name '*.sqlite' | grep -q .

  echo "== idempotent reinstall"
  env -i HOME="$HOMEDIR" PATH="$CLEAN_PATH" TERM=dumb FINDPLUS_YES=1 \
    FINDPLUS_WHEEL="$WHEEL" bash "$REPO/install.sh" 2>&1 | tee "$WORK/reinstall.log"
  grep -qi upgrade "$WORK/reinstall.log"

  echo "== uninstall"
  env -i HOME="$HOMEDIR" PATH="$CLEAN_PATH" TERM=dumb bash "$REPO/install.sh" \
    --uninstall --yes 2>&1 | tee "$WORK/uninstall.log"
  test ! -e "$HOMEDIR/.local/share/findplus"
  test ! -e "$HOMEDIR/.local/bin/findplus"
  grep -F "$HOMEDIR/.findplus" "$WORK/uninstall.log"
  test -d "$HOMEDIR/.findplus"

  echo REHEARSAL-MACOS-PASS
}

linux_leg() {
  docker image pull python:3.12 >/dev/null
  docker run --rm --volume "$REPO":/src:ro --workdir /src python:3.12 \
    bash packaging/scripts/rehearsal-linux-inner.sh
}

case "$MODE" in
  macos) build_wheel; macos_leg ;;
  linux) build_wheel; linux_leg ;;
  all)   build_wheel; macos_leg; linux_leg ;;
  *) echo "usage: rehearse-fresh-machine.sh [macos|linux|all]" >&2; exit 2 ;;
esac

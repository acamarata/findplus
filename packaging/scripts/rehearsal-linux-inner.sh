#!/usr/bin/env bash
# rehearsal-linux-inner.sh — the container side of the fresh-machine rehearsal.
#
# Purpose    : Run the same install.sh contract asserts as the macOS leg on a
#              machine that has nothing but Python 3.12, to prove a Linux user
#              can install and run Find+ from the wheel alone.
# Inputs     : /src mounted read-only (the repo), /src/dist holding the wheel.
# Outputs    : the asserts' output, and REHEARSAL-LINUX-PASS as the last line.
# Constraints: no privilege escalation, no real home, serves on port 18647 so
#              nothing collides with a daemon on 8647. A doctor finding about a
#              missing Chrome is recorded output on Linux, never a failure.
# Reuse      : install.sh:main, exercised unchanged.
set -euo pipefail

HOMEDIR=/tmp/fp-home
PATH=/usr/local/bin:/usr/bin:/bin
export PATH
mkdir -p "$HOMEDIR"
WHEEL=""
for w in /src/dist/findplus-*-py3-none-any.whl; do
  [ -f "$w" ] && WHEEL="$w"
done
test -n "$WHEEL"
LOG=/tmp/fp-rehearsal-logs
mkdir -p "$LOG"

echo "== wheel: $WHEEL"

echo "== fresh install"
env -i HOME="$HOMEDIR" PATH="$PATH" TERM=dumb FINDPLUS_YES=1 FINDPLUS_WHEEL="$WHEEL" \
  bash /src/install.sh 2>&1 | tee "$LOG/install.log"
grep -q "Python:" "$LOG/install.log"
grep -q "Venv:" "$LOG/install.log"
grep -q "Symlink:" "$LOG/install.log"
grep -q "Package:" "$LOG/install.log"

FPBIN="$HOMEDIR/.local/bin/findplus"
test -x "$FPBIN"
VER=$(basename "$WHEEL" | cut -d- -f2)
"$FPBIN" --version | grep -F "$VER"

echo "== doctor"
HOME="$HOMEDIR" "$FPBIN" doctor > "$LOG/doctor.log" 2>&1 || true
grep -F "not signed-in" "$LOG/doctor.log"
cat "$LOG/doctor.log"

echo "== auth --help"
HOME="$HOMEDIR" "$FPBIN" auth --help > /dev/null

echo "== serve and probe"
env -i HOME="$HOMEDIR" PATH="$PATH" TERM=dumb "$FPBIN" serve --no-poller --port 18647 &
PID=$!
curl -fsS --retry 30 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:18647/api/health | grep -F '"app":"findplus"'
kill "$PID"
wait "$PID" 2>/dev/null || true

echo "== state isolation"
find "$HOMEDIR/.findplus" -name '*.sqlite' | grep -q .

echo "== idempotent reinstall"
env -i HOME="$HOMEDIR" PATH="$PATH" TERM=dumb FINDPLUS_YES=1 FINDPLUS_WHEEL="$WHEEL" \
  bash /src/install.sh 2>&1 | tee "$LOG/reinstall.log"
grep -qi upgrade "$LOG/reinstall.log"

echo "== uninstall"
env -i HOME="$HOMEDIR" PATH="$PATH" TERM=dumb bash /src/install.sh --uninstall --yes \
  2>&1 | tee "$LOG/uninstall.log"
test ! -e "$HOMEDIR/.local/share/findplus"
test ! -e "$HOMEDIR/.local/bin/findplus"
grep -F "$HOMEDIR/.findplus" "$LOG/uninstall.log"
test -d "$HOMEDIR/.findplus"

echo "== findplus setup (headless, D-P2-10)"
env -i HOME="$HOMEDIR" PATH="$PATH" TERM=dumb FINDPLUS_YES=1 FINDPLUS_WHEEL="$WHEEL" \
  bash /src/install.sh 2>&1 | tee "$LOG/reinstall-for-setup.log"
env -i HOME="$HOMEDIR" PATH="$PATH" TERM=dumb "$FPBIN" setup --yes \
  2>&1 | tee "$LOG/setup.log"
if grep -qi traceback "$LOG/setup.log"; then
  echo "FAIL: findplus setup --yes raised a Python traceback" >&2
  exit 1
fi
env -i HOME="$HOMEDIR" PATH="$PATH" TERM=dumb "$FPBIN" serve --no-poller --port 18647 &
PID2=$!
curl -fsS --retry 30 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:18647/api/health | grep -F '"app":"findplus"'
curl -fsS http://127.0.0.1:18647/api/settings | tee "$LOG/settings-after-setup.json" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['onboarding.last_step'] == 'headless', d; assert d['onboarding.completed_at'] is None, d"
cat "$LOG/settings-after-setup.json"
kill "$PID2"
wait "$PID2" 2>/dev/null || true

echo REHEARSAL-LINUX-PASS

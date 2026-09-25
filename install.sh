#!/usr/bin/env bash
# install.sh - Find+ curl-pipe installer. Env: FINDPLUS_YES/VERSION/WHEEL/PREFIX/BIN/STATE_DIR. Flags: --yes --uninstall --version X.
# Idempotent, never sudo; --uninstall keeps the state dir; --start runs setup and start after installing.
# See .github/wiki/Install.md, .github/wiki/Uninstall.md, packaging-and-release.md.
set -euo pipefail

YES="${FINDPLUS_YES:-0}"
UNINSTALL=0
STARTNOW=0
VERSION_PIN="${FINDPLUS_VERSION:-1.1.1}"

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes) YES=1; shift ;;
      --uninstall) UNINSTALL=1; shift ;;
      --start) STARTNOW=1; shift ;;
      --version) VERSION_PIN="${2:?install.sh: --version needs a value, e.g. --version 1.0.0}"; shift 2 ;;
      *) echo "install.sh: unknown argument: $1" >&2; exit 2 ;;
    esac
  done
}

find_python() {
  # Debian/Ubuntu split venv into python3-venv; skip to the next candidate instead of failing outright.
  local novenv=""
  for candidate in python3.13 python3.12 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c 'import sys; assert (3, 12) <= sys.version_info < (3, 15)' 2>/dev/null || continue
    "$candidate" -c 'import venv, ensurepip' 2>/dev/null && { PYTHON="$candidate"; return 0; }
    novenv="$candidate"
  done
  # Telling someone holding a working 3.12.3 to go and get 3.12 is useless.
  if [ -n "$novenv" ]; then
    pkg=$("$novenv" -c 'import sys;print(f"python{sys.version_info[0]}.{sys.version_info[1]}-venv")')
    echo "find+: $novenv has no venv module (Debian ships it apart): sudo apt install $pkg" >&2
    exit 1
  fi
  found=$(python3 -c 'import sys;print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)
  echo "find+: Python 3.12-3.14 with venv required (python3 here: $found); get one via your package manager, python.org or 'uv python install 3.12', then rerun" >&2
  exit 1
}

PREFIX="${FINDPLUS_PREFIX:-$HOME/.local/share/findplus}"
BIN="${FINDPLUS_BIN:-$HOME/.local/bin}"
VENV="$PREFIX/venv"
SYMLINK="$BIN/findplus"
STATE_DIR="${FINDPLUS_STATE_DIR:-$HOME/.findplus}"

uninstall() {
  # The service and watchdog must be unloaded BEFORE the venv goes: launchd and
  # systemd keep restarting a program whose file has just been deleted, and
  # once `findplus` is gone there is nothing left that knows the unit paths.
  if [ -x "$VENV/bin/findplus" ]; then
    echo "Unloading the service and watchdog"
    "$VENV/bin/findplus" uninstall --yes || echo "install.sh: service uninstall reported an error; removing files anyway" >&2
  else
    echo "install.sh: $VENV/bin/findplus is missing, so no service could be unloaded." >&2
    echo "  If a service is still installed, remove it by hand (also in .github/wiki/Uninstall.md):" >&2
    echo "    macOS:   launchctl bootout gui/\$(id -u)/com.acamarata.findplus" >&2
    echo "             launchctl bootout gui/\$(id -u)/com.acamarata.findplus.watchdog" >&2
    echo "             rm -f ~/Library/LaunchAgents/com.acamarata.findplus*.plist" >&2
    echo "    Linux:   systemctl --user disable --now findplus.service findplus-watchdog.timer" >&2
    echo "             rm -f ~/.config/systemd/user/findplus*" >&2
    echo "    Windows: schtasks /delete /tn FindPlus /f" >&2
    echo "             schtasks /delete /tn FindPlusWatchdog /f" >&2
  fi
  echo "Removing $VENV and $SYMLINK"
  rm -rf "$VENV"
  rm -f "$SYMLINK"
  rmdir "$PREFIX" 2>/dev/null || true
  echo "State directory $STATE_DIR left intact."
  exit 0
}

# findplus is not on PyPI yet, so `findplus==<ver>` resolves to nothing and the
# README's one-liner ends in "Could not find a version that satisfies". Fall
# back to the GitHub release sdist, the source gen-formula.sh already uses.
package_spec() {
  local pin="${FINDPLUS_WHEEL:-${FINDPLUS_SDIST_URL:-}}"
  [ -n "$pin" ] && { echo "$pin"; return; }
  [ -z "$VERSION_PIN" ] && { echo findplus; return; }
  curl -fsI "https://pypi.org/pypi/findplus/$VERSION_PIN/json" > /dev/null 2>&1 &&
    { echo "findplus==$VERSION_PIN"; return; }
  echo "https://github.com/${FINDPLUS_REPO:-acamarata/findplus}/releases/download/v$VERSION_PIN/findplus-$VERSION_PIN.tar.gz"
}

print_plan() {
  echo "  Python:  $PYTHON ($("$PYTHON" --version))"
  echo "  Venv:    $VENV"
  echo "  Symlink: $SYMLINK"
  echo "  Package: $(package_spec)"
}

install() {
  mkdir -p "$PREFIX" "$BIN"
  local package
  package="$(package_spec)"
  # A venv whose interpreter is gone (OS upgrade, removed python) made pip die
  # rc=127, and re-running the one-liner -- the documented remedy -- could not fix it.
  if [ -d "$VENV" ] && ! "$VENV/bin/python" -c pass 2>/dev/null; then
    echo "Existing venv is broken (interpreter gone); rebuilding"; rm -rf "$VENV"
  fi
  if [ -d "$VENV" ]; then
    echo "Existing venv found, running pip install --upgrade"
    "$VENV/bin/pip" install --upgrade --quiet "$package"
  else
    "$PYTHON" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet "$package"
  fi
  ln -sf "$VENV/bin/findplus" "$SYMLINK"
  if [ "$STARTNOW" = "1" ]; then
    # setup --yes never signs anyone in, so a fresh --start always reaches
    # `start --yes` unauthenticated, which exits 4. That is the expected end of
    # a first install, not a failure: capture it, name the next command, exit 0.
    "$SYMLINK" setup --yes || true
    START_RC=0
    "$SYMLINK" start --yes || START_RC=$?
    if [ "$START_RC" = "4" ]; then
      echo "Installed. Sign in with: findplus auth"
    elif [ "$START_RC" != "0" ]; then
      exit "$START_RC"
    fi
  else
    echo "Installed. Run: findplus setup   (or findplus auth && findplus start)"
  fi
  # $BIN is off the default macOS PATH; Debian's ~/.profile adds it only if it existed at login.
  if ! command -v findplus >/dev/null 2>&1; then
    echo "$BIN is not on your PATH -- until it is, run $SYMLINK directly. To add it:"
    echo "  echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.profile   # then open a new shell"
  fi
}

main() {
  parse_args "$@"

  if [ "$UNINSTALL" = "1" ]; then
    uninstall
  fi

  find_python

  print_plan
  if [ "$YES" != "1" ]; then
    printf "Continue? [y/N] "
    # [ -r /dev/tty ] passes inside a container while opening it fails with
    # ENXIO, which killed the curl-pipe install under set -e. Probe by opening.
    if (exec 3</dev/tty) 2>/dev/null; then read -r answer </dev/tty; else read -r answer || true; fi
    case "${answer:-}" in
      y | Y) ;;
      *) echo "Aborted."; exit 1 ;;
    esac
  fi

  install
}

main "$@"

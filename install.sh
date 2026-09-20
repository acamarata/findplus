#!/usr/bin/env bash
# install.sh - Find+ curl-pipe installer. Env: FINDPLUS_YES/VERSION/WHEEL/PREFIX/BIN/STATE_DIR. Flags: --yes --uninstall --version X.
# Idempotent, never sudo; --uninstall keeps the state dir. See .github/wiki/Install.md, .github/wiki/Uninstall.md, packaging-and-release.md.
set -euo pipefail

YES="${FINDPLUS_YES:-0}"
UNINSTALL=0
VERSION_PIN="${FINDPLUS_VERSION:-1.0.0}"

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes) YES=1; shift ;;
      --uninstall) UNINSTALL=1; shift ;;
      --version) VERSION_PIN="${2:?install.sh: --version needs a value, e.g. --version 1.0.0}"; shift 2 ;;
      *) echo "install.sh: unknown argument: $1" >&2; exit 2 ;;
    esac
  done
}

find_python() {
  # Debian/Ubuntu split venv into python3-venv; skip to the next candidate instead of failing outright.
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; assert (3, 12) <= sys.version_info < (3, 15)' 2>/dev/null &&
        "$candidate" -c 'import venv, ensurepip' 2>/dev/null; then
        PYTHON="$candidate"
        return 0
      fi
    fi
  done
  echo "find+: Python 3.12-3.14 with the venv module required" >&2
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

package_spec() {
  echo "${FINDPLUS_WHEEL:-findplus${VERSION_PIN:+==$VERSION_PIN}}"
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
  if [ -d "$VENV" ]; then
    echo "Existing venv found, running pip install --upgrade"
    "$VENV/bin/pip" install --upgrade --quiet "$package"
  else
    "$PYTHON" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet "$package"
  fi
  ln -sf "$VENV/bin/findplus" "$SYMLINK"
  echo "Installed. Run: findplus auth"
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

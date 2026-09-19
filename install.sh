#!/usr/bin/env bash
# install.sh — Find+ curl-pipe installer.
#
# Purpose    : Install findplus into an isolated venv under FINDPLUS_PREFIX
#              and symlink its entry point into FINDPLUS_BIN, with no sudo.
# Inputs     : env FINDPLUS_YES, FINDPLUS_VERSION, FINDPLUS_WHEEL,
#              FINDPLUS_PREFIX, FINDPLUS_BIN; flags --yes, --uninstall,
#              --version X.
# Outputs    : $FINDPLUS_PREFIX/venv (installed package), a symlink at
#              $FINDPLUS_BIN/findplus.
# Constraints: idempotent (existing venv upgrades in place); never sudo;
#              --uninstall removes the venv+symlink but leaves the state
#              directory untouched.
set -euo pipefail

YES="${FINDPLUS_YES:-0}"
UNINSTALL=0
VERSION_PIN="${FINDPLUS_VERSION:-}"

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes)
        YES=1
        shift
        ;;
      --uninstall)
        UNINSTALL=1
        shift
        ;;
      --version)
        VERSION_PIN="${2:?install.sh: --version needs a value, e.g. --version 1.0.0}"
        shift 2
        ;;
      *)
        echo "install.sh: unknown argument: $1" >&2
        exit 2
        ;;
    esac
  done
}

find_python() {
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; assert (3, 12) <= sys.version_info < (3, 15)' 2>/dev/null; then
        PYTHON="$candidate"
        return 0
      fi
    fi
  done
  echo "find+: Python 3.12-3.14 required" >&2
  exit 1
}

PREFIX="${FINDPLUS_PREFIX:-$HOME/.local/share/findplus}"
BIN="${FINDPLUS_BIN:-$HOME/.local/bin}"
VENV="$PREFIX/venv"
SYMLINK="$BIN/findplus"
STATE_DIR="${FINDPLUS_STATE_DIR:-$HOME/.findplus}"

uninstall() {
  echo "Removing $VENV and $SYMLINK"
  rm -rf "$VENV"
  rm -f "$SYMLINK"
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
    if [ -r /dev/tty ]; then read -r answer </dev/tty; else read -r answer; fi
    case "$answer" in
      y | Y) ;;
      *)
        echo "Aborted."
        exit 1
        ;;
    esac
  fi

  install
}

main "$@"

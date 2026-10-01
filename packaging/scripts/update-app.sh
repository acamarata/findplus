#!/usr/bin/env bash
# update-app.sh: update Find+.app in place, even while it is running.
#
# Purpose    : Finder refuses to replace an app that is open. This quits Find+
#              (and its background daemon) cleanly, swaps in the new app, and
#              starts it again. Your history and settings live in ~/.findplus
#              and are never touched.
# Inputs     : no args = download the latest release dmg from GitHub, verify its
#              sha256, install it. --dmg PATH installs a dmg you already have;
#              --app PATH installs an already-built Find+.app (developers).
#              --no-launch skips the relaunch. APP_DIR overrides /Applications.
# Outputs    : APP_DIR/Find+.app replaced; the old one is deleted only after the
#              new one is in place. Never uses sudo.
# Constraints: macOS Apple Silicon only. Requires curl, hdiutil, ditto, osascript.
set -euo pipefail

REPO="acamarata/findplus"
APP_DIR="${APP_DIR:-/Applications}"
APP="$APP_DIR/Find+.app"
LAUNCH=1
SRC_DMG=""
SRC_APP=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dmg) SRC_DMG="${2:?update: --dmg needs a path}"; shift 2 ;;
    --app) SRC_APP="${2:?update: --app needs a path}"; shift 2 ;;
    --no-launch) LAUNCH=0; shift ;;
    *) echo "update: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ "$(uname)" = Darwin ] || { echo "update: this updates the macOS app only. For the CLI, rerun install.sh." >&2; exit 1; }

TMP="$(mktemp -d)"
MNT=""
cleanup() {
  [ -n "$MNT" ] && hdiutil detach "$MNT" -quiet 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

fetch_latest_dmg() {
  echo "update: looking up the latest release..."
  local json url sha_url
  json="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")"
  url="$(printf '%s' "$json" | grep -o '"browser_download_url": *"[^"]*aarch64\.dmg"' | head -1 | sed 's/.*"\(https[^"]*\)"/\1/')"
  sha_url="${url}.sha256"
  [ -n "$url" ] || { echo "update: no Apple Silicon dmg in the latest release." >&2; exit 1; }
  echo "update: downloading $(basename "$url")"
  curl -fL --progress-bar -o "$TMP/app.dmg" "$url"
  curl -fsSL -o "$TMP/app.dmg.sha256" "$sha_url"
  local want got
  want="$(awk '{print $1}' "$TMP/app.dmg.sha256")"
  got="$(shasum -a 256 "$TMP/app.dmg" | awk '{print $1}')"
  [ "$want" = "$got" ] || { echo "update: checksum mismatch, nothing installed." >&2; exit 1; }
  SRC_DMG="$TMP/app.dmg"
}

mount_dmg() {
  MNT="$(hdiutil attach "$SRC_DMG" -nobrowse -readonly -mountrandom "$TMP" | awk 'END{print $NF}')"
  SRC_APP="$MNT/Find+.app"
}

quit_running() {
  # pgrep -f takes a regex, and "Find+" has a "+" in it.
  local pat
  # shellcheck disable=SC2016  # a sed script, not a shell expansion
  pat="$(printf '%s' "$APP/Contents/MacOS" | sed 's/[][\\.*+?^$(){}|]/\\&/g')"
  if pgrep -f "$pat" >/dev/null 2>&1; then
    echo "update: quitting Find+..."
    osascript -e 'tell application id "com.acamarata.findplus" to quit' >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
      pgrep -f "$pat" >/dev/null 2>&1 || break
      sleep 0.5
    done
    # The tray app can ignore a polite quit, and it restarts its daemon when the
    # daemon dies. Stop what is left of this app only, until nothing is left,
    # so no old process is still running while the files are swapped.
    for _ in $(seq 1 10); do
      pkill -f "$pat" 2>/dev/null || break
      sleep 1
      pgrep -f "$pat" >/dev/null 2>&1 || break
    done
  fi
}

if [ -z "$SRC_APP" ]; then
  [ -n "$SRC_DMG" ] || fetch_latest_dmg
  mount_dmg
fi
[ -d "$SRC_APP" ] || { echo "update: $SRC_APP not found." >&2; exit 1; }

NEW_VER="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$SRC_APP/Contents/Info.plist")"
OLD_VER="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$APP/Contents/Info.plist" 2>/dev/null || echo none)"
echo "update: Find+ $OLD_VER -> $NEW_VER"

quit_running
ditto "$SRC_APP" "$APP.new"
rm -rf "$APP.old"
[ -d "$APP" ] && mv "$APP" "$APP.old"
mv "$APP.new" "$APP"
rm -rf "$APP.old"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
echo "update: installed Find+ $NEW_VER in $APP_DIR"

if [ "$LAUNCH" = 1 ]; then
  open "$APP"
  echo "update: Find+ is starting (look for F+ in the menu bar)."
fi

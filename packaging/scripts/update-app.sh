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
#              --force installs an app whose code signature does not verify, or
#              that another developer signed (it stays quarantined, so macOS
#              still asks before opening it).
#              Used by the app itself: --verify-only runs every check and stops
#              before anything is quit; --wait-pid PID waits for the app to exit
#              first; --result FILE gets "ok <version>" or "failed <reason>".
# Outputs    : APP_DIR/Find+.app replaced; the old one is deleted only after the
#              new one is in place, and put back if the swap fails. When the app
#              was quit and the update then fails, the old app is started again.
#              Never uses sudo.
# Constraints: macOS Apple Silicon only. Requires curl, hdiutil, ditto, codesign.
#              A new app signed by a different team than the installed one is
#              refused (without --force).
set -euo pipefail

REPO="acamarata/findplus"
APP_DIR="${APP_DIR:-/Applications}"
APP="$APP_DIR/Find+.app"
LAUNCH=1
FORCE=0
VERIFY_ONLY=0
WAIT_PID=""
RESULT=""
SRC_DMG=""
SRC_APP=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dmg) SRC_DMG="${2:?update: --dmg needs a path}"; shift 2 ;;
    --app) SRC_APP="${2:?update: --app needs a path}"; shift 2 ;;
    --no-launch) LAUNCH=0; shift ;;
    --force) FORCE=1; shift ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    --wait-pid) WAIT_PID="${2:?update: --wait-pid needs a pid}"; shift 2 ;;
    --result) RESULT="${2:?update: --result needs a path}"; shift 2 ;;
    *) echo "update: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ "$(uname)" = Darwin ] || { echo "update: this updates the macOS app only. For the CLI, rerun install.sh." >&2; exit 1; }

TMP="$(mktemp -d)"
MNT=""
QUIT=0      # 1 once Find+ has been quit: a failure from then on starts it again
DONE=0      # 1 once the new app is in place
FAIL_MSG=""
NEW_VER=""

on_exit() {
  local code=$?
  [ -n "$MNT" ] && hdiutil detach "$MNT" -quiet 2>/dev/null || true
  rm -rf "$TMP"
  if [ "$DONE" = 1 ] || [ "$VERIFY_ONLY" = 1 ]; then return; fi
  if [ -n "$RESULT" ]; then printf 'failed %s\n' "${FAIL_MSG:-exit $code}" > "$RESULT" || true; fi
  if [ "$QUIT" = 1 ] && [ "$LAUNCH" = 1 ] && [ -d "$APP" ]; then
    echo "update: starting the Find+ you already had." >&2
    open "$APP" || true
  fi
}
trap on_exit EXIT

fail() { FAIL_MSG="$1"; echo "update: $1" >&2; exit 1; }

fetch_latest_dmg() {
  echo "update: looking up the latest release..."
  local json url sha_url
  json="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")"
  url="$(printf '%s' "$json" | grep -o '"browser_download_url": *"[^"]*aarch64\.dmg"' | head -1 | sed 's/.*"\(https[^"]*\)"/\1/')"
  sha_url="${url}.sha256"
  [ -n "$url" ] || fail "no Apple Silicon dmg in the latest release."
  echo "update: downloading $(basename "$url")"
  curl -fL --progress-bar -o "$TMP/app.dmg" "$url"
  curl -fsSL -o "$TMP/app.dmg.sha256" "$sha_url"
  local want got
  want="$(awk '{print $1}' "$TMP/app.dmg.sha256")"
  got="$(shasum -a 256 "$TMP/app.dmg" | awk '{print $1}')"
  [ "$want" = "$got" ] || fail "checksum mismatch, nothing installed."
  SRC_DMG="$TMP/app.dmg"
}

mount_dmg() {
  MNT="$(hdiutil attach "$SRC_DMG" -nobrowse -readonly -mountrandom "$TMP" | awk 'END{print $NF}')"
  SRC_APP="$MNT/Find+.app"
}

app_pattern() {
  # pgrep -f takes a regex, and "Find+" has a "+" in it.
  # shellcheck disable=SC2016  # a sed script, not a shell expansion
  printf '%s' "$APP/Contents/MacOS" | sed 's/[][\\.*+?^$(){}|]/\\&/g'
}

wait_for_pid() {
  # The app started this run and quits itself; give it time to stop its daemon.
  QUIT=1
  for _ in $(seq 1 60); do
    kill -0 "$WAIT_PID" 2>/dev/null || return 0
    sleep 0.5
  done
  echo "update: Find+ did not quit within 30 seconds; stopping what is left."
}

quit_running() {
  local pat
  pat="$(app_pattern)"
  if pgrep -f "$pat" >/dev/null 2>&1; then
    QUIT=1
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

# Checks that can refuse run BEFORE anything is quit or moved.
check_arm64() {
  # uname -m says x86_64 inside a Rosetta shell, so ask the hardware.
  [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = 1 ] \
    || fail "this Mac is not Apple Silicon; the app is arm64 only."
  local exe
  exe="$SRC_APP/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print CFBundleExecutable' "$SRC_APP/Contents/Info.plist" 2>/dev/null || echo findplus)"
  lipo -archs "$exe" 2>/dev/null | grep -qw arm64 \
    || fail "the new app has no arm64 build, nothing installed."
}

SIGNED=1
check_signature() {
  if ! codesign --verify --deep --strict "$SRC_APP" >/dev/null 2>&1; then
    SIGNED=0
    if [ "$FORCE" != 1 ]; then
      echo "update: rerun with --force if you built it yourself and trust it." >&2
      fail "the new app's code signature does not verify, nothing installed."
    fi
    echo "update: signature does not verify; installing anyway (--force). It stays quarantined."
  fi
}

team_id() {
  # The signing team of a bundle, or nothing for an unsigned or ad-hoc one.
  codesign -dv --verbose=2 "$1" 2>&1 | sed -n 's/^TeamIdentifier=//p' | grep -v '^not set$' | head -1 || true
}

check_team() {
  # An app signed by one developer is only ever replaced by an app from the same one.
  [ -d "$APP" ] || return 0
  local old new
  old="$(team_id "$APP")"
  [ -n "$old" ] || return 0
  new="$(team_id "$SRC_APP")"
  [ "$new" = "$old" ] && return 0
  if [ "$FORCE" = 1 ]; then
    echo "update: signed by team ${new:-none}, not $old; installing anyway (--force)."
    SIGNED=0
    return 0
  fi
  fail "the new app is signed by team ${new:-none}, not $old like the installed one, nothing installed."
}

swap_in() {
  rm -rf "$APP.new"   # a leftover from an interrupted run would be merged into by ditto
  ditto "$SRC_APP" "$APP.new"
  rm -rf "$APP.old"
  if [ -d "$APP" ]; then mv "$APP" "$APP.old"; fi
  if ! mv "$APP.new" "$APP"; then
    rm -rf "$APP.new"
    if [ -d "$APP.old" ]; then mv "$APP.old" "$APP"; fi
    fail "could not put the new app in place; the old one is back."
  fi
  rm -rf "$APP.old"
}

if [ -z "$SRC_APP" ]; then
  [ -n "$SRC_DMG" ] || fetch_latest_dmg
  mount_dmg
fi
[ -d "$SRC_APP" ] || fail "$SRC_APP not found."

NEW_VER="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$SRC_APP/Contents/Info.plist")"
OLD_VER="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$APP/Contents/Info.plist" 2>/dev/null || echo none)"
echo "update: Find+ $OLD_VER -> $NEW_VER"

check_arm64
check_signature
check_team
if [ "$VERIFY_ONLY" = 1 ]; then
  echo "update: Find+ $NEW_VER passed every check."
  exit 0
fi
if [ -n "$WAIT_PID" ]; then wait_for_pid; fi
quit_running
swap_in
DONE=1
# Only a verified app loses its quarantine flag; an unverified one keeps it.
if [ "$SIGNED" = 1 ]; then xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true; fi
echo "update: installed Find+ $NEW_VER in $APP_DIR"
if [ -n "$RESULT" ]; then printf 'ok %s\n' "$NEW_VER" > "$RESULT" || true; fi

# If Find+ runs its daemon as a login service, quitting the app stopped it and
# launchd will not bring it back by itself. Start it again from the new app.
# `print` matches the exact label (a grep also matched ...findplus.watchdog).
LABEL="com.acamarata.findplus"
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true
fi

if [ "$LAUNCH" = 1 ]; then
  open "$APP"
  echo "update: Find+ is starting (look for F+ in the menu bar)."
fi

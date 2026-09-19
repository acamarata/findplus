#!/usr/bin/env bash
set -euo pipefail
# embed-widget.sh — embed the signed FindPlusWidgetExtension.appex into
# Find+.app, re-sign inner-to-outer, re-notarise, and rebuild the dmg.
#
# Purpose    : Step 5 of the release build (specs/desktop-app.md § Build &
#              sign): without this the widget never appears in the
#              Notification Center gallery on an end-user machine.
# Inputs     : $APP_PATH (default: the bundle `cargo tauri build
#              --target aarch64-apple-darwin` emits, the same BUNDLE_DIR
#              release-local.sh uses); APPLE_SIGNING_IDENTITY and, for
#              notarisation, APPLE_API_KEY_P8_BASE64 + APPLE_API_KEY_ID +
#              APPLE_API_ISSUER_ID; cli/pyproject.toml (for VERSION).
# Outputs    : Signed, embedded Find+.app; dist/FindPlus-<ver>-aarch64.dmg.
# Constraints: Idempotent (safe to re-run); sign inner-to-outer, never
#              --deep; no credentials logged.

# --- GUARD ------------------------------------------------------------------
IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
if [ -z "$IDENTITY" ]; then
  echo "FAIL: APPLE_SIGNING_IDENTITY is not set" >&2
  exit 1
fi

# Same credential names and decoding as release-local.sh: the App Store Connect
# key arrives base64-encoded in the environment, never as a file on disk.
NOTARISE=false
API_KEY_FILE=""
if [ -n "${APPLE_API_KEY_P8_BASE64:-}" ] && [ -n "${APPLE_API_KEY_ID:-}" ] &&
  [ -n "${APPLE_API_ISSUER_ID:-}" ]; then
  NOTARISE=true
fi

# --- LOCATE_APP ---------------------------------------------------------------
APP_PATH="${APP_PATH:-desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/macos/Find+.app}"
if [ ! -d "$APP_PATH" ]; then
  echo "FAIL: $APP_PATH not found. Run cargo tauri build first." >&2
  exit 1
fi

# --- LOCATE_APPEX -------------------------------------------------------------
APPEX_BUILD_DIR="desktop/widget/build/Build/Products/Release"
APPEX_NAME="FindPlusWidgetExtension.appex"
APPEX_PATH="$APPEX_BUILD_DIR/$APPEX_NAME"

if [ ! -d "$APPEX_PATH" ]; then
  echo "No pre-built appex found; building it now."
  xcodebuild -project desktop/widget/FindPlusWidget.xcodeproj \
    -scheme FindPlusWidgetExtension -configuration Release -arch arm64 build \
    -derivedDataPath desktop/widget/build ONLY_ACTIVE_ARCH=NO CODE_SIGNING_ALLOWED=NO
fi

if [ ! -d "$APPEX_PATH" ]; then
  echo "FAIL: appex still not found at $APPEX_PATH after build" >&2
  exit 1
fi

# --- EMBED --------------------------------------------------------------------
PLUGINS_DIR="$APP_PATH/Contents/PlugIns"
mkdir -p "$PLUGINS_DIR"
rm -rf "${PLUGINS_DIR:?}/$APPEX_NAME"
cp -R "$APPEX_PATH" "$PLUGINS_DIR/"

# The helper is gitignored build output: build it when it is absent, rather
# than silently shipping an app whose findplus://refresh-widget does nothing.
RELOAD_HELPER="desktop/widget/reload-widgets"
if [ ! -f "$RELOAD_HELPER" ]; then
  swiftc "$RELOAD_HELPER.swift" -framework WidgetKit -o "$RELOAD_HELPER"
fi
cp "$RELOAD_HELPER" "$APP_PATH/Contents/MacOS/"

# --- SIGN_INNER -----------------------------------------------------------
codesign --force --options runtime --timestamp \
  --entitlements desktop/widget/FindPlusWidget.entitlements \
  --sign "$IDENTITY" "$PLUGINS_DIR/$APPEX_NAME"

# --- SIGN_HELPER --------------------------------------------------------------
# Every Mach-O inside the bundle must carry its own hardened-runtime signature
# or notarisation rejects the app; --deep is never used, so the outer sign does
# not cover this one. No entitlements: the helper only talks to widgetkitd.
codesign --force --options runtime --timestamp \
  --sign "$IDENTITY" "$APP_PATH/Contents/MacOS/reload-widgets"

# --- SIGN_OUTER -------------------------------------------------------------
codesign --force --options runtime --timestamp \
  --entitlements desktop/src-tauri/entitlements.plist \
  --sign "$IDENTITY" "$APP_PATH"

# --- NOTARISE -----------------------------------------------------------------
if [ "$NOTARISE" = true ]; then
  API_KEY_FILE=$(mktemp -t findplus-api-key)
  trap 'rm -f "$API_KEY_FILE"' EXIT
  echo "$APPLE_API_KEY_P8_BASE64" | base64 -d >"$API_KEY_FILE"
  xcrun notarytool submit "$APP_PATH" \
    --key "$API_KEY_FILE" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER_ID" --wait
  xcrun stapler staple "$APP_PATH"
else
  echo "APPLE_API_KEY_P8_BASE64 not set; skipping notarisation."
fi

# --- REBUILD_DMG --------------------------------------------------------------
if ! command -v create-dmg >/dev/null 2>&1; then
  brew install create-dmg
fi

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('cli/pyproject.toml','rb'))['project']['version'])")
# One canonical dmg name for the whole project: FindPlus-<ver>-<arch>.dmg
# (findplus PRI § Names). No -arm64 spelling anywhere.
DMG_NAME="FindPlus-${VERSION}-aarch64.dmg"
mkdir -p dist
rm -f "dist/$DMG_NAME"
create-dmg --volname "Find+" \
  --background desktop/src-tauri/icons/dmg-background.png \
  --window-size 660 400 \
  --icon "Find+" 180 170 \
  --app-drop-link 480 170 \
  "dist/$DMG_NAME" "$APP_PATH"

# --- VERIFY -------------------------------------------------------------------
codesign --verify --deep --strict --verbose=2 "$APP_PATH" 2>&1
# spctl --type install only passes on a notarised, stapled bundle, so it is a
# real check after notarisation and a guaranteed failure without it.
if [ "$NOTARISE" = true ]; then
  spctl -a -vv --type install "$APP_PATH" 2>&1
else
  echo "Not notarised; skipping spctl --type install (it would reject by design)."
fi
echo "dmg: dist/$DMG_NAME"
echo "Run 'pluginkit -m -p com.apple.widgetkit-extension | grep findplus' after first launch."

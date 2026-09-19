#!/usr/bin/env bash
set -euo pipefail
# embed-widget.sh — embed the signed FindPlusWidgetExtension.appex into
# Find+.app, re-sign inner-to-outer, re-notarise, and rebuild the dmg.
#
# Purpose    : Step 5 of the release build (specs/desktop-app.md § Build &
#              sign): without this the widget never appears in the
#              Notification Center gallery on an end-user machine.
# Inputs     : dist/macos/Find+.app (from `cargo tauri build`);
#              APPLE_SIGNING_IDENTITY, APPLE_API_KEY, APPLE_API_KEY_ID,
#              APPLE_API_ISSUER env vars; cli/pyproject.toml (for VERSION).
# Outputs    : Signed, embedded Find+.app; rebuilt dist/FindPlus-*.dmg.
# Constraints: Idempotent (safe to re-run); sign inner-to-outer, never
#              --deep; no credentials logged.

# --- GUARD ------------------------------------------------------------------
IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
if [ -z "$IDENTITY" ]; then
  echo "FAIL: APPLE_SIGNING_IDENTITY is not set" >&2
  exit 1
fi

NOTARISE=false
if [ -n "${APPLE_API_KEY:-}" ] && [ -n "${APPLE_API_KEY_ID:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ]; then
  NOTARISE=true
fi

# --- LOCATE_APP ---------------------------------------------------------------
APP_PATH="${APP_PATH:-dist/macos/Find+.app}"
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

RELOAD_HELPER="desktop/widget/reload-widgets"
if [ -f "$RELOAD_HELPER" ]; then
  cp "$RELOAD_HELPER" "$APP_PATH/Contents/MacOS/"
fi

# --- SIGN_INNER -----------------------------------------------------------
codesign --force --options runtime --timestamp \
  --entitlements desktop/widget/FindPlusWidget.entitlements \
  --sign "$IDENTITY" "$PLUGINS_DIR/$APPEX_NAME"

# --- SIGN_OUTER -------------------------------------------------------------
codesign --force --options runtime --timestamp \
  --entitlements desktop/src-tauri/entitlements.plist \
  --sign "$IDENTITY" "$APP_PATH"

# --- NOTARISE -----------------------------------------------------------------
if [ "$NOTARISE" = true ]; then
  xcrun notarytool submit "$APP_PATH" \
    --key "$APPLE_API_KEY" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER" --wait
  xcrun stapler staple "$APP_PATH"
fi

# --- REBUILD_DMG --------------------------------------------------------------
if ! command -v create-dmg >/dev/null 2>&1; then
  brew install create-dmg
fi

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('cli/pyproject.toml','rb'))['project']['version'])")
DMG_NAME="FindPlus-${VERSION}-arm64.dmg"
rm -f "dist/$DMG_NAME"
create-dmg --volname "Find+" \
  --background desktop/src-tauri/icons/dmg-background.png \
  --window-size 660 400 \
  --icon "Find+" 180 170 \
  --app-drop-link 480 170 \
  "dist/$DMG_NAME" "$APP_PATH"

# --- VERIFY -------------------------------------------------------------------
codesign --verify --deep --strict --verbose=2 "$APP_PATH" 2>&1
spctl -a -vv --type install "$APP_PATH" 2>&1
echo "Run 'pluginkit -m -p com.apple.widgetkit-extension | grep findplus' after first launch."

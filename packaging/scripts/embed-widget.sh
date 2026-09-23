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
#              release-local.sh uses); $ARCH_SUFFIX (default: aarch64 — the
#              dmg name token; the release.yml matrix passes x86_64 on its
#              Intel leg, APP_PATH pointed at that leg's own
#              target/x86_64-apple-darwin bundle); APPLE_SIGNING_IDENTITY
#              and, for notarisation, APPLE_API_KEY_P8_BASE64 +
#              APPLE_API_KEY_ID + APPLE_API_ISSUER_ID; cli/pyproject.toml
#              (for VERSION).
# Outputs    : Signed, embedded Find+.app; dist/FindPlus-<ver>-<arch>.dmg.
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
# Which arch token the final dmg name carries. Defaults to aarch64 to match
# the default APP_PATH above (the arm64-only local build release-local.sh
# still runs); the release.yml matrix's Intel leg overrides both together.
ARCH_SUFFIX="${ARCH_SUFFIX:-aarch64}"
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

# --- REPAIR_SIDECAR -----------------------------------------------------------
# The Tauri bundler copies bundle.resources with symlinks dereferenced, which
# turns the sidecar's Python.framework into a plain directory holding a second
# copy of the binary. The notary service then rejects both copies with "the
# signature of the binary is invalid", because a framework's seal is only valid
# inside a correctly linked framework. Restoring the tree with cp -R, from the
# staged copy sign-sidecar.sh already signed, keeps the symlinks and the
# signatures and drops about 12 MB of duplicated binary.
SIDECAR_SRC="desktop/src-tauri/resources/findplus-daemon"
SIDECAR_DEST="$APP_PATH/Contents/Resources/resources"
if [ -d "$SIDECAR_SRC" ] && [ -d "$SIDECAR_DEST/findplus-daemon" ]; then
  echo "Restoring the sidecar tree with its symlinks"
  rm -rf "${SIDECAR_DEST:?}/findplus-daemon"
  cp -R "$SIDECAR_SRC" "$SIDECAR_DEST/"
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

# --- SIGN_LAUNCHER --------------------------------------------------------------
# tauri.conf.json's externalBin ("binaries/findplus-daemon") places a small
# launcher (execs the real sidecar from Contents/Resources/resources/
# findplus-daemon/) directly at Contents/MacOS/findplus-daemon. cargo tauri
# build never signs it (no macOS signingIdentity is set there by design; every
# signature in this bundle comes from this script), and it is a distinct
# Mach-O from the PyInstaller sidecar sign-sidecar.sh already signed under
# Contents/Resources/resources/, so the outer non-deep sign below rejects the
# bundle with "code object is not signed at all" until this runs first.
codesign --force --options runtime --timestamp \
  --sign "$IDENTITY" "$APP_PATH/Contents/MacOS/findplus-daemon"

# --- SIGN_OUTER -------------------------------------------------------------
codesign --force --options runtime --timestamp \
  --entitlements desktop/src-tauri/entitlements.plist \
  --sign "$IDENTITY" "$APP_PATH"

# --- NOTARISE -----------------------------------------------------------------
if [ "$NOTARISE" = true ]; then
  API_KEY_FILE=$(mktemp -t findplus-api-key)
  NOTARISE_ZIP=$(mktemp -d)/FindPlus.zip
  trap 'rm -f "$API_KEY_FILE" "$NOTARISE_ZIP"' EXIT
  echo "$APPLE_API_KEY_P8_BASE64" | base64 -d >"$API_KEY_FILE"
  # notarytool accepts only .zip, .dmg and .pkg. Handing it a .app bundle
  # directory fails with "Unable to process file: invalid file type", so the
  # bundle is zipped with ditto (which preserves the signature and symlinks)
  # and the ticket is stapled back onto the original .app afterwards.
  ditto -c -k --keepParent "$APP_PATH" "$NOTARISE_ZIP"
  xcrun notarytool submit "$NOTARISE_ZIP" \
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
DMG_NAME="FindPlus-${VERSION}-${ARCH_SUFFIX}.dmg"
mkdir -p dist
rm -f "dist/$DMG_NAME"
# --icon takes the item's name as it appears in the mounted volume, which for
# an app bundle includes the .app suffix; without it create-dmg's AppleScript
# cannot find the item and the positioning step fails.
# create-dmg exits 2 when it cannot detach the scratch volume even though the
# dmg is written, so its status is checked rather than left to `set -e`.
create-dmg --volname "Find+" \
  --background desktop/src-tauri/icons/dmg-background.png \
  --window-size 660 400 \
  --icon "Find+.app" 180 170 \
  --app-drop-link 480 170 \
  "dist/$DMG_NAME" "$APP_PATH" || true
if [ ! -f "dist/$DMG_NAME" ]; then
  echo "FAIL: create-dmg did not produce dist/$DMG_NAME" >&2
  exit 1
fi

# --- SIGN_AND_NOTARISE_DMG ----------------------------------------------------
# The app inside is stapled, but the disk image itself carried no signature, so
# Gatekeeper rejected the download with "no usable signature" before the user
# ever reached the app. Sign, notarise and staple the image too.
codesign --force --timestamp --sign "$IDENTITY" "dist/$DMG_NAME"
if [ "$NOTARISE" = true ]; then
  xcrun notarytool submit "dist/$DMG_NAME" \
    --key "$API_KEY_FILE" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER_ID" --wait
  xcrun stapler staple "dist/$DMG_NAME"
fi

# --- VERIFY -------------------------------------------------------------------
# The published v1.0.0 dmg shipped web/.claude/{AGENTS,CLAUDE}.md inside the
# notarised app: the Intel spec still copied the tree verbatim, and no release
# step ever looked inside a built bundle (E1 packaging round 3 F2). The specs
# are fixed and unit-tested, but a spec test cannot see what was actually
# bundled, so the bundle itself is checked here before it is signed off.
if find "$APP_PATH" -path '*/.claude/*' -print -quit | grep -q .; then
  echo "embed-widget.sh: .claude/ found inside $APP_PATH -- rebuild the sidecar." >&2
  find "$APP_PATH" -path '*/.claude/*' >&2
  exit 1
fi

codesign --verify --deep --strict --verbose=2 "$APP_PATH" 2>&1
# spctl --type exec only passes on a notarised, stapled bundle, so it is a
# real check after notarisation and a guaranteed failure without it.
if [ "$NOTARISE" = true ]; then
  spctl -a -vv --type exec "$APP_PATH" 2>&1
else
  echo "Not notarised; skipping spctl --type exec (it would reject by design)."
fi
echo "dmg: dist/$DMG_NAME"
echo "Run 'pluginkit -m -p com.apple.widgetkit-extension | grep findplus' after first launch."

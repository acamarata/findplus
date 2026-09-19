#!/usr/bin/env bash
# embed-widget.sh — copy the built WidgetKit extension into the app bundle
# and re-sign the outer .app (Gatekeeper checks the outer seal after any
# change to bundle contents).
#
# Purpose    : Final assembly step between `cargo tauri build` (T6 step 4)
#              and the release verification (T6 step 6).
# Inputs     : APPLE_SIGNING_IDENTITY env var; xcodebuild's DerivedData output.
# Outputs    : Find+.app/Contents/PlugIns/FindPlusWidget.appex, re-signed app.
# Constraints: Re-notarise + `xcrun stapler staple` separately (this script
#              only embeds and re-signs); widget build itself is E15/E16.
set -euo pipefail

APP="desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/macos/Find+.app"

if [ ! -d "$APP" ]; then
  echo "FAIL: app bundle not found: $APP (run cargo tauri build first)" >&2
  exit 1
fi

APPEX=$(find "$HOME/Library/Developer/Xcode/DerivedData" \
  -name "FindPlusWidget.appex" -type d 2>/dev/null | head -1 || true)

if [ -z "$APPEX" ]; then
  echo "FAIL: FindPlusWidget.appex not found under DerivedData (build the widget first)" >&2
  exit 1
fi

mkdir -p "$APP/Contents/PlugIns"
cp -R "$APPEX" "$APP/Contents/PlugIns/FindPlusWidget.appex"

if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  codesign --force --options runtime --timestamp \
    --sign "$APPLE_SIGNING_IDENTITY" "$APP/Contents/PlugIns/FindPlusWidget.appex"
  codesign --force --options runtime --timestamp \
    --sign "$APPLE_SIGNING_IDENTITY" "$APP"
fi

echo "embed-widget: done (re-notarise separately with xcrun notarytool + xcrun stapler)"

# FindPlusWidget

A native macOS WidgetKit extension for Find+. It reads `GET /api/widget` over the loopback API
only — it never opens `~/.findplus` directly (App Sandbox, no App Groups).

## Build

```
xcodegen generate
xcodebuild -project FindPlusWidget.xcodeproj -scheme FindPlusWidgetExtension \
  -configuration Debug -arch arm64 build CODE_SIGNING_ALLOWED=NO
```

`CODE_SIGNING_ALLOWED=NO` builds without a certificate for local development. The release build
is signed by `packaging/scripts/embed-widget.sh` with the Developer ID identity, matching
specs/desktop-app.md § Build & sign step 3/5.

## Test

```
xcodebuild -project FindPlusWidget.xcodeproj -scheme FindPlusWidgetTests \
  -configuration Debug -arch arm64 test -destination 'platform=macOS,arch=arm64'
```

## Embed

`packaging/scripts/embed-widget.sh` copies `FindPlusWidgetExtension.appex` into
`Find+.app/Contents/PlugIns/`, signs it with the same Developer ID identity and hardened runtime
as the outer app, then re-signs the outer app and re-notarises. After the app's first launch,
verify the extension registered with:

```
pluginkit -m -p com.apple.widgetkit-extension | grep findplus
```

## Widget gallery

The widget appears under "Find+" in the macOS widget gallery in three sizes: small, medium, and
large. Small shows state + tracked count + newest fix age; medium adds up to three device rows;
large adds group verdicts and an optional map preview.

Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks.

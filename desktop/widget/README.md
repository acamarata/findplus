# FindPlusWidget

A native macOS WidgetKit extension for Find+. It reads `GET /api/widget` over the loopback API
only — it never opens `~/.findplus` directly (App Sandbox, no App Groups).

**Known limitation (G2):** with no App Groups entitlement, the widget has no channel to learn a
non-default daemon port, so it always assumes `DaemonPort.fallbackPort` (`Sources/Provider.swift`)
— a daemon started with `FINDPLUS_PORT` set to anything other than 8647 will not be reachable from
the widget until App Groups (or another shared-container mechanism) is wired up, a signing and
provisioning change scoped separately from this constant.

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

The status widget appears under "Find+" in the macOS widget gallery in three sizes: small,
medium, and large. Small shows state + tracked count + newest fix age; medium adds up to three
device rows; large adds group verdicts and an optional map preview.

A second widget, "Find+ Places", appears as its own gallery entry in two sizes: small (up to two
places) and medium (up to four, plus the last presence change time). Both show each place's name
and badges for whoever is inside, reusing `GET /api/widget`'s `places` array (`Model.swift`) and
the same icon/colour lookup the status widget uses for its device rows.

Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks.

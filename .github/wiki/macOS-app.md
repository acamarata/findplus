# macOS app

Find+.app is a menu-bar shell (Tauri 2) around the same daemon the CLI runs,
with a WidgetKit widget for Notification Center.

## Menu-bar icon states

| State | Meaning |
|---|---|
| Green dot | Daemon reachable, polling normally. |
| Amber dot | Daemon reachable but stale (past the poll interval), or notarisation/sign issue. |
| Red dot | Daemon unreachable. Use "Restart daemon" from the menu. |

The menu also shows the most recent fix, a Lock item, a "Start at login"
toggle, and Quit.

## Widget

Add the widget from System Settings -> Widgets -> Find+, or Notification
Center's Edit Widgets in earlier macOS versions. It shows tracked device
count, group presence, and the most recent fix, refreshed whenever the
daemon polls. Toggle the map preview on the large widget with
`findplus widget show-map on` or `off`; force an immediate refresh with
`findplus widget refresh`.

## Gatekeeper

On first launch, right-click Find+.app and choose **Open**, since the app
is not notarised through the Mac App Store review process. Subsequent
launches open normally.

## Sidecar architecture

The Python daemon is bundled inside Find+.app as a PyInstaller sidecar
(`Contents/Resources/`), started and supervised by the Tauri shell. It is
the same daemon the CLI installs; the app never runs a second copy.

## Widget manual checklist

Deferred to 1.1: PlacesWidget.

- [ ] Gallery shows three sizes (systemSmall, systemMedium, systemLarge)
- [ ] Locked state shows lock glyph and 'Locked', no device data
- [ ] Poll Now intent triggers a poll (check daemon log)
- [ ] Open Find+ intent opens the dashboard
- [ ] Dark mode: all text and dots adapt, no hardcoded light colours

---
[[Home]]

# macOS app

Find+.app is a menu-bar shell (Tauri 2) around the same daemon the CLI runs,
with a WidgetKit widget for Notification Center.

## Menu-bar icon states

| State | Dot | Meaning |
|---|---|---|
| Ok | Green | Daemon reachable and polling normally. |
| Stale | Amber | Daemon reachable, but the last poll is older than twice the poll interval. |
| Error | Red | Sign-in needed, a decryption error, or three or more failed polls in a row. |
| Locked | Grey | The app lock is on. No location data is shown until you unlock. |
| Down | Grey | Find+ is not running. "Restart daemon" appears when it was running and stopped. |

The menu also shows the most recent fix (hidden while locked or down), the
tracked device count, Poll Now, Lock, Open Dashboard, Settings, Open App and
Quit Find+. "Start at login" is in the Settings window, not the menu.

## Widget

Add the widget from System Settings -> Widgets -> Find+, or Notification
Center's Edit Widgets in earlier macOS versions. It shows tracked device
count, group presence, and the most recent fix, refreshed whenever the
daemon polls. Toggle the map preview on the large widget with
`findplus widget show-map on` or `off`; force an immediate refresh with
`findplus widget refresh`.

The headline age, the freshness dot and the large widget's map snapshot all
describe the device with the **newest** fix, whatever it is called. A device
whose last fix is older than the stale threshold is shown with no place and no
map: a missing fix is not evidence of where a tag is.

The small widget shows status only. It carries no action buttons; at that size
a mis-tap is too easy, and Poll Now and Lock are both one click away in the
menu bar.

## Places widget

A second widget, "Find+ Places", shows who is at each saved place: its name,
badges for whoever is currently inside (a device badge, or a group badge when
every one of a group's members is there together), and how long ago that
changed. A place with no one inside reads "Nobody here". Add it the same way
as the status widget, then pick "Find+ Places" instead of "Find+". The small
size shows up to two places; medium shows up to four and adds the last
change time. Tapping the widget opens the dashboard's Places tab.

Locked and offline states behave exactly like the status widget: no place
names or badges are shown, only the lock glyph or "Find+ is not running".

## Gatekeeper

Find+ is distributed outside the Mac App Store. Release builds are signed
with a Developer ID and notarised by Apple, so they open normally.

A build produced without signing credentials is published with `-UNSIGNED`
in its filename. For one of those, right-click Find+.app and choose **Open**
the first time; later launches open normally.

To check a build yourself, assess it as an executable, not as an installer:

```bash
spctl -a -vv --type exec /Applications/Find+.app
```

`--type install` is for installer packages and reports `rejected` on an app
bundle whatever its signature.

## Sidecar architecture

The Python daemon is bundled inside Find+.app as a PyInstaller sidecar
(`Contents/Resources/`), started and supervised by the Tauri shell. It is
the same daemon the CLI installs; the app never runs a second copy.

## Widget manual checklist

- [ ] Gallery shows three sizes (systemSmall, systemMedium, systemLarge)
- [ ] systemSmall shows no action buttons
- [ ] The headline device is the newest fix, not the first name alphabetically
- [ ] Locked state shows lock glyph and 'Locked', no device data
- [ ] Poll Now intent triggers a poll (check daemon log)
- [ ] Open Find+ intent opens the dashboard
- [ ] Dark mode: all text and dots adapt, no hardcoded light colours

## Places widget manual checklist

- [ ] Gallery shows "Find+ Places" as a separate gallery entry, two sizes
      (systemSmall, systemMedium)
- [ ] A place with someone inside shows their device/group badge(s)
- [ ] A place with no one inside reads "Nobody here"
- [ ] A fully-present group shows its own badge, not one badge per member
- [ ] Locked state shows lock glyph and 'Locked', no place data
- [ ] Tapping the widget opens the dashboard on the Places tab
- [ ] Dark mode: all text and badges adapt, no hardcoded light colours

---
[[Home]]

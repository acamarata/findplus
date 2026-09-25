# Changelog

All notable changes to Find+ are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-09-21

### Added
- `alerts deliveries --json` prints the delivery log as JSON, matching `alerts rules list --json`.
- The place dialog can now fill its coordinates two ways instead of only a map click: "Use a tracker's last location" picks any tracked device's most recent fix, and an opt-in address search (type an address, press Search) queries OpenStreetMap's Nominatim through the daemon, never the browser, only when you press the button.
- The Places tab's side panel lists every saved place, with its color, radius and who is currently inside it, plus Edit, Delete and click-to-centre on each row.
- Devices and groups can now use a custom uploaded PNG as their badge icon, alongside the bundled Lucide glyphs and letter badges. Upload one from the icon picker's "Your icons" section; an icon still in use cannot be deleted. The macOS widget cannot fetch images, so a custom icon shows there as a letter badge instead.
- A second macOS widget, "Find+ Places": who is at each saved place right now, with a device or group badge per occupant and the last time it changed. Tapping it opens the dashboard's Places tab.
- A failed Telegram, WhatsApp or webhook alert now retries automatically when the failure looks temporary (a timeout, a "too many requests" response, or a server error): up to three more tries, one minute, five minutes, then thirty minutes after the first failure. A rejected request, a bad credential or an unconfigured channel is not retried. The delivery log shows a retry in progress and how many tries a delivery has used.
- The macOS app release now ships an Intel dmg (`FindPlus-<version>-x86_64.dmg`) alongside the existing Apple Silicon one (`FindPlus-<version>-aarch64.dmg`); the release workflow builds, signs and notarises both natively on their own runners.
- The macOS app opens the dashboard by itself on a first launch, so the setup wizard is the first thing you see, and goes back to being tray-only once setup is finished. The splash window now closes when the daemon is up, instead of staying on top until you quit.
- Settings now carries the poll interval, how long history is kept, whether Mac notifications may name the person and place, and a Run setup again button.
- A fresh install opens the setup wizard by itself. If you go somewhere else first, a bar under the toolbar offers to resume it, and stays until setup is actually finished.
- The wizard's last four steps: saved places, alert channels, the app lock, and a summary. Every channel shows what it does with your alert text before you can switch it on.
- The wizard's first four steps: what Find+ is, signing in to Google or Apple, choosing which trackers to poll, and putting them in a group. Every step can be skipped and none of them is a dead end.
- A sign-in panel at the top of the Settings dialog, for Google Find Hub and Apple Find My. The Google card follows the Chrome sign-in as it runs and offers a download link when Chrome is missing; the Apple card asks for the two-factor code when Apple wants one.
- An onboarding wizard for the dashboard. The daemon remembers which step you reached in `onboarding.last_step` and whether you finished in `onboarding.completed_at`, both readable on `GET /api/settings` and writable per key, so closing the tab halfway resumes where you left off.
- Sign in to Google Find Hub from the dashboard: `POST /api/auth/google/start` opens Chrome and `GET /api/auth/google/progress` reports how far along it is. Chrome now runs in a profile of its own under `~/.findplus/chrome-profile`, so signing in no longer closes the Chrome windows you already have open.
- Sign in to Apple Find My from the dashboard, 2FA included: `POST /api/auth/apple/start` then `POST /api/auth/apple/code`. Your Apple password is used for the sign-in call and is never stored, logged or sent back.
- `GET /api/auth/status` reports, per provider, whether you are signed in, which account, and what is still missing (Chrome, or the Apple extra).
- `findplus auth --status` prints that same report as a table, or as JSON with `--json`.
- Register an Apple Find My accessory from the dashboard's Apple card, by choosing a key file (a `.plist` export or a `.json` holding the base64 private key): `POST /api/apple/accessories`. A tag you have already registered asks before it is replaced, rather than quietly replacing or silently refusing it.
- `findplus doctor` now checks the Chrome profile directory is owner-only, and repairs it with `--repair`.
- `findplus setup`, a guided first-run walkthrough in the terminal for installs that never open the dashboard. Pass `--yes` to accept every default without a prompt.
- The daemon prunes location history, place visits and group events older than the retention window once a day, with no restart needed after changing it.
- `install.sh --start` installs, runs the setup wizard and starts the service in one command. A fresh install finishes by asking you to sign in, which is a success, not an error.
- The Alerts tab has a Delivery log showing each alert's rule, channel, kind, message text and body, time, status and error.
- An Uninstall page in the wiki with the manual service-removal commands for macOS, Linux and Windows.
- A bundled Lucide icon sprite (48 icons, ISC licensed) the dashboard loads once at startup.
- An icon picker for device and group badges: the 48 bundled icons grouped by kind, a letter of your choice, or a plain colored dot.
- A color picker for device and group badges: the 12 palette colors, or any color you pick.
- One badge renderer behind the map markers, the timeline track heads and the group legend, so a device's icon and color look the same everywhere.
- An i18n scaffold for the dashboard: `web/app/i18n.js` and the English catalog at `web/locales/en.json`, whose honesty sentences are generated from the same source the API serves. Every string the dashboard shows now comes from that catalog, so a second language can replace one file.
- A phone-width layout: under 600px the dashboard gets a bottom tab bar, the toolbar collapses behind a More button, dialogs open full screen, and every button and tick box is at least 44px to tap.
- WCAG 2.1 AA groundwork: page landmarks, a label on every form control, a visible focus ring, a focus trap and Escape-to-close on the Devices and Settings dialogs, an announced alert banner, and color changes where text or a control border fell short of the contrast minimum.
- An accessibility scan in the browser test suite: axe-core over every tab, in both themes, at desktop and phone width.
- An alert rule can now pick any combination of Telegram, webhook, WhatsApp and Mac notifications, through a checkbox set in the rule form and a repeatable `--channel` option on `findplus alerts rules add`. Mac notifications only appear as a choice on macOS.
- Native macOS notifications for alerts. The daemon queues them and the menu bar app shows them, so an alert arrives even with no dashboard window open. While Find+ is locked, or unless you turn notification details on, the banner says only "Find+ alert", because a notification preview can appear on a locked screen.
- WhatsApp alerts, relayed through CallMeBot. The setup text says plainly that your alert text passes through a third party before it reaches WhatsApp. Set it up in the Alerts tab, which carries that text and the CallMeBot contact details, or from the terminal with `findplus alerts whatsapp set`/`clear`; the routes behind it are `PUT`/`DELETE /api/alerts/channels/whatsapp`. The phone number is shown masked and the API key is never returned.
- Alert rules can target more than one channel at once. Each channel gets its own delivery row and its own cooldown, so a notification on one never suppresses another.
- Device and group labels, icons and colors: `PATCH /api/devices/{id}`, `GET /api/icons`, `findplus devices label`/`findplus devices icons`, exports and the macOS widget all carry the new fields. A label is local only and survives every provider name refresh.
- Edit a device's label, icon and color from the dashboard: every row in the Devices dialog has an Edit button, and the choice shows up on the device list, on every map marker, on the timeline track heads and in the macOS widget.
- A group create and edit dialog on the Groups tab: name, icon, color, quorum, cluster radius, stale-after minutes and which tracked devices belong to the group.
- Group cards on the Groups tab, each with the group badge, its member avatars, its live presence verdict, and edit and delete buttons.

### Changed
- `findplus devices`' request-rate hint names "requests" generically instead of always saying "Google requests/hour", so it reads right for an Apple-only setup.
- Alert rule cards and `alerts rules list` show channel names like "Desktop notification" and "WhatsApp" instead of raw ids such as `native`/`whatsapp`.
- CLI and dialog device counts use the right singular or plural ("1 device tracked" vs "6 devices tracked") instead of always "device(s)".
- CI runs the accessibility scan, the icon and catalog drift check, and the Rust notification tests as three lanes of their own, so each failure names itself.
- README and wiki screenshots are regenerated at 1280x800, with a matching phone-width set at 375x812.
- The Chrome-not-found message is one sentence now shared by the terminal, the API and `/api/config`, instead of two wordings that could drift apart.
- Starting a sign-in requires the request to carry an `Origin` or `Sec-Fetch-Site` header. Browsers and the desktop app always send one; nothing else has a reason to start a sign-in.
- `PUT /api/settings` is now `PATCH /api/settings`, and its body carries the poll interval, the history retention period and whether native notifications may show details.
- The Homebrew caveats and the installer both point new installs at `findplus setup`, so every install channel gives the same first instruction.
- `findplus start` finishes a fresh sign-in in one run: it discovers devices from every provider you are signed in to, shows them, tracks them all and installs the service. Pass `--no-track-all` to discover without tracking.
- `findplus start` exits 4 when you are not signed in yet, instead of 0, and counts an Apple sign-in as being signed in.
- `install.sh` is shorter and points at a new Uninstall wiki page for the manual service-removal commands it prints. Without `--start` its last line now points at `findplus setup`.
- `findplus start` asks "Install and start the service now? [Y/n]" in an interactive terminal instead of only printing "Pass --yes"; a script or pipe with no terminal still needs `--yes`.
- `findplus devices` lists from the local database by default instead of always re-querying Find Hub, so it works without a signed-in account; `--refresh` opts back into the live query. It also gained a Label column, and `--json` carries the field.
- `findplus alerts rules list` and `findplus devices` render their tables with the same aligned-column helper, fixing a jammed header and missing columns in the alerts table.
- A wrong PIN on the lock screen now shows the server's real "Incorrect PIN" message with a pointer to `findplus lock reset`, instead of the generic word "Locked".
- `findplus lock reset` is a new, easier-to-find name for the existing PIN-recovery command, alongside `findplus reset-lock` and `findplus pin reset`.

### Fixed
- The place dialog is now styled like the device and group editors, instead of painting as an unstyled browser-default strip across the map, and "Add place" opens it directly at the map's current centre -- no map click required, so it is fully keyboard-reachable.
- The map's starting view fits your tracked devices' latest fixes, or your saved places when none has reported yet, instead of always opening on a hardcoded US-centred view regardless of where your trackers actually are.
- The bottom tab bar on a phone-width dashboard stays clickable once the page is scrolled, instead of the map's overlay layer painting over it.
- The bundled icon sprite no longer leaves a blank band above the toolbar.
- The test suite's warning filters name the specific warnings Find+ suppresses, instead of ignoring every deprecation warning.
- `findplus devices --json` prints the device list as JSON, as the CLI reference documents.
- `GET /api/devices` rows carry the `groups` and `presence` keys the API contract documents.
- The menu bar shows a "CLI daemon vX (app is vY)" line when the daemon and the app disagree on version, instead of only writing it to the log.
- An alert rule whose channel has no credentials now records a `skipped` delivery instead of silently discarding the event.
- `GET /api/places/events?group_id=` returns that group members' events instead of always returning an empty list.
- `install.sh` no longer aborts with a `/dev/tty` error where no terminal is readable, such as inside a container.
- The MCP server instructions name both Google Find Hub and Apple Find My, instead of claiming every tracker reports through Find Hub.
- `findplus serve --host` now refuses a non-loopback address unless `FINDPLUS_ALLOW_PUBLIC_BIND=1` is set, matching `findplus config set HOST` and the `Settings.host` guard.
- The daemon answers 503 with the repair command on an unmigrated database, instead of 500.
- The dashboard no longer breaks when `/api/config` returns an error while the notices are loading.
- A group crossing recorded twice in the same instant is stored once, and the duplicate no longer discards the rest of the poll's location history.
- Upgrading a database that already contained duplicate group events now succeeds instead of leaving the daemon unable to start.
- The widget's large view hides the map for a device whose last fix is stale, and the small view no longer shows buttons it cannot action.
- The dashboard footer names each tracking network only when a device of that kind is tracked, instead of naming Google Find Hub for every tracker, and clears both sentences while the app is locked.
- The page sources behind the dashboard are no longer reachable under `/static`, in any capitalisation.
- An alert delivery error is stored with credentials masked, so a webhook key in a failing request URL is not shown in the Delivery log.
- A group whose members have mostly gone quiet is no longer labelled "Diverged" when only one is still reporting.
- Every stale group member shows how long since its last fix, instead of "no fix for unknown".
- The dashboard and the MCP server name the tracking network each device actually uses, instead of naming Google Find Hub for every tracker.
- "Refresh from your providers" now asks every provider you are signed in to, and says which one it could not reach instead of showing a raw error.
- Alerts carry the documented latency sentence, and a long group note is kept whole rather than cut mid-sentence.
- GPX and KML exports carry a device's label, falling back to its device ID when no label is set, instead of leaving the name and description blank.
- A CallMeBot phone number is now redacted in logs and CLI output, instead of appearing in the clear next to the API key.
- The widget shows the device with the newest fix rather than the first by name, spells a long gap in days, and names group verdicts the way the dashboard does.
- The lock screen states that locking does not encrypt the database, which until now was only visible in Settings, behind the lock.
- The Delivery log shows times in your local timezone and says why an alert was skipped.
- The group presence lists say which members are together and which are away.
- The installer pins the released version, tells you when `~/.local/bin` is not on your PATH, names the package to install when `venv` is missing, and rebuilds a virtualenv whose Python has gone.
- The macOS app bundle no longer carries the repository's editor configuration files.
- The Homebrew formula points at the release the tag actually published.
- The Windows scheduled task no longer kills the daemon every hour. Its time limit was capped at one hour by mistake; it now runs unlimited, like the macOS and Linux service managers already did.
- A database upgrade that adds columns to `devices`, `groups` or `alert_rules` no longer deletes rows from related tables such as group members and alert rules along the way.
- Downgrading a database that already has WhatsApp or Mac-notification alert deliveries in it no longer fails; those rows are remapped to their nearest 1.0 status instead of blocking the migration.
- A Telegram bot token or CallMeBot API key that is malformed, for example from a hand-edited config file, is rejected before Find+ ever sends it anywhere, instead of being placed into a request URL.
- A cross-site form post that carries a Referer header but no Origin or Sec-Fetch-Site header, such as one aimed at registering an Apple accessory, is now refused like any other cross-site request.
- The setup wizard renders inside a proper card with the same field and button styling as the rest of the app, instead of raw, unstyled rows, and offers WhatsApp as an inline setup step alongside Telegram.
- A group's CSV, JSON, GPX and KML exports now carry each member's label, falling back to its device ID when no label is set, the same as a single device's export already did.
- Pressing Next on the setup wizard's app lock step with a PIN typed and confirmed now sets it, instead of silently discarding it; a mismatched pair shows an inline error and stays on the step instead of advancing with no lock set.
- Apple Find My fixes carry the accuracy the source actually gives, which is none: Find+ no longer invents a metres figure from Apple's confidence label. The dashboard now shows "Accuracy unknown" for these fixes instead of a made-up `±N m` reading, and a database upgrade nulls out any invented figures a previous version already stored. A saved place's own accuracy, when copied from an invented Apple observation, is nulled by the same migration.
- Map marker popups show the tracker's display name as the heading, instead of the time.
- Devices, groups, the map, the timeline and the macOS widget now read a device or group's label before its raw provider name almost everywhere that still showed the raw name: the Edit button and dialog title, group presence sentences, and the widget's device rows and letter badges.
- The place dialog's tracker picker no longer lists every device twice the first time "Add place" is opened, and picking a tracker's location or an address-search result now shows "Location set from <name>." and pans the map to it.
- The setup wizard's device-label input no longer gets squeezed unreadable at 375px width.
- The wizard's Places step refreshes its list and re-fits the map after a place is added, instead of showing a stale list until the wizard reopens.
- The wizard's alerts-latency notice shows once, instead of once per channel, and the Telegram token field is wide enough to show its placeholder.
- The dashboard tabs sit in a navigation landmark with a `tablist` role, and the alerts tab's scrollable tables carry an explicit region role, for screen readers.
- Alert text shows a fix's time in local time with its zone, instead of a bare timestamp.
- The place dialog's Search/Use buttons and the place card's Edit/Delete buttons use the app's own button styling instead of unstyled browser defaults.
- Timeline rows show the saved place name for a fix inside it, instead of only its coordinates.
- The alerts Delivery log is readable at 360px as labelled cards instead of a squeezed table; a channel with no stored credentials is flagged instead of silently disabled, so a fresh install can still create its first rule; and a rejected Telegram token's raw server detail is replaced with a plain-language message.
- The wizard's Devices step gets a visible "Track" column header, every device defaults to ticked on a fresh account with nothing tracked yet, and pressing Next with nothing ticked asks for confirmation first instead of silently tracking nothing.
- The wizard's sign-in step has a heading, and the Google button reflects whether you are already signed in.
- The wizard's "configure later" webhook link opens the Alerts tab, instead of pointing at a dead Settings anchor.
- The wizard's summary step shows how many devices were actually tracked, and both the wizard and dashboard group dialogs block saving a group with no members selected, instead of showing "Unknown" with no explanation.
- Declining sign-in during `findplus setup` leaves onboarding open to resume later, instead of marking it complete.
- The dashboard no longer fires authenticated API calls, and no longer logs 401 errors, while Find+ is locked.
- The custom-icon upload starts as soon as a file is chosen, instead of requiring a separate Upload click.
- The phone-width tab bar draws its icons from the app's own SVG sprite instead of emoji glyphs, which rendered inconsistently across platforms and fonts.
- The poll-interval field in Settings shows a plain-language message next to the field when the value is out of range, instead of the raw config error at the top of the dialog.
- Chrome detection matches the same install locations the underlying Google Find Hub library searches, and the missing-Chrome notice only shows when Chrome is actually needed, instead of by default.
- The alerts rule dialog is titled and styled like the place/group/device dialogs, defaults its channel checkboxes to whichever are actually connected instead of always ticking Telegram, and refuses to save a rule with nothing connected selected.
- Every inline style the delivery log's column widths used is in CSS now, clearing the console errors they caused under the dashboard's Content-Security-Policy.

- Alerts rules render as stacked cards inside the narrow side pane, with Edit and Delete inside it, instead of a table too wide for the pane to show.
- Places, Groups and the macOS widget now agree on one staleness window, instead of Places and the widget using a 90-minute cutoff while a group's own cutoff disagreed with no explanation.
- The Delivery log shows the sent text and body for every channel, not only desktop notifications; a WhatsApp row no longer claims its message "is not logged" when it is.
- A stale group member's note counts minutes up to two hours, instead of rounding "94 minutes" straight to "1 h".
- The Chrome-not-found notice on the sign-in step and in Settings shows only when you are actually signed out and Chrome is missing, instead of also showing while you are signed in.
- Settings shows a Switch account button once you are signed in to a provider.
- The More menu closes on Escape or a tap outside it, and returns focus to the More button.
- The More menu's Lock item is hidden until a PIN is actually set, instead of opening a lock screen that any PIN dismisses.
- The group dialog's cluster-radius hint sits on its own line under the slider instead of squeezed beside it, and a group card's Edit and Delete buttons share one row instead of wrapping.
- The Groups tab's presence panel refreshes after you save or delete the selected group, instead of showing the old verdict until you reselect it.
- `alerts deliveries` and `alerts rules list` print local time and a plain yes/no, instead of raw UTC timestamps and Python's True/False.
- The wizard's token, phone, API key and device-label fields carry accessible names for screen readers, and the phone field shows an example number.
- The wizard's welcome step says plainly what leaves the machine (sign-in, alert channels you connect, map tiles, and opt-in address search) instead of a blanket claim that nothing does except Google or Apple sign-in, and no longer lists map tiles among the things you turn on, since they always load.
- The first-run wizard's map shows your tracked devices' latest fixes before the dashboard has ever booted, instead of only place circles with no trackers on it; its zoom and attribution controls are readable in dark mode.
- The wizard's Groups step name field has a visible label, and its app-lock step shows a PIN error next to the field instead of a plain-grey line below the whole form.
- The wizard's Done step shows the real tracked-device count after a reload resumes it partway through, instead of "0 devices tracked".
- The wizard's Groups and Devices steps show their own errors inline instead of writing them to a hidden banner, so a duplicate group name or a failed device save is no longer silent.
- Saving a place or group whose name is already in use shows a plain sentence instead of the raw server error.
- Poll Now disables itself for the remaining cooldown instead of letting a second click fail with a console error.
- The wizard's Places step gives its Add place button room above the map instead of sitting flush against it.
- `findplus status` checks the daemon's own bound port, instead of the default, so it reports correctly when the daemon runs on a custom port.
- Settings' confirm-PIN field is linked to its mismatch error for screen readers, and a new PIN attempt clears the old top-of-dialog message instead of leaving it next to the new field error.
- The phone-width topbar's More label sits centred in its button, instead of pinned to the top.

### Security
- The local API's Host and Origin checks now also require the daemon's own bound port, not just the loopback hostname, closing a DNS-rebinding gap where a page could name any port it liked and still get past the guard. The check reads the port the daemon actually bound to, not a config value that could change while it runs.

## [1.0.0] - 2026-09-19

### Added
- Location history daemon for Google Find Hub trackers (Moto Tag and compatible).
- Apple Find My support for accessories whose pairing keys are available (optional `findplus[apple]` extra).
- FastAPI HTTP server at http://127.0.0.1:8647 with a vanilla-JS dashboard including an interactive Leaflet map.
- SQLite database via Alembic migrations; automatic schema upgrade on start.
- Click CLI: auth, devices, poll-now, serve, start, stop, restart, status, doctor, open, export, prune, config, db, providers, places, groups, alerts, mcp, version, widget.
- User-level service management via LaunchAgent (macOS), systemd user unit (Linux), and Task Scheduler (Windows).
- Places and geofence alerts: circular geofences with configurable enter/exit confirmation counts and hysteresis.
- Group presence tracking with quorum semantics (any/majority/all/N), cluster radius, and stale-after threshold.
- Telegram bot alerts with long-poll setup flow and webhook alternative.
- MCP server (stdio) exposing location, place, group, and alert query tools to LLM clients.
- macOS menu-bar app (Tauri 2) with a WidgetKit widget showing live device and group presence.
- PyInstaller sidecar bundled inside the macOS app.
- App lock with PIN; lock does not encrypt the database (see Privacy).
- Multi-provider architecture: pluggable provider interface for future tracker support.
- CLI export to CSV, JSON, GPX, and KML with group support (one track per member).
- `findplus doctor` with --repair flag; `findplus version --check` against GitHub releases.

[Unreleased]: https://github.com/acamarata/findplus/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/acamarata/findplus/releases/tag/v1.0.0

# Changelog

All notable changes to Find+ are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
- Register an Apple Find My accessory from the dashboard, by uploading a key plist (up to 64 KiB) or pasting a private key: `POST /api/apple/accessories`. A tag you have already registered is reported rather than quietly replaced.
- `findplus doctor` now checks the Chrome profile directory is owner-only, and repairs it with `--repair`.
- `findplus setup`, a guided first-run walkthrough in the terminal for installs that never open the dashboard. Pass `--yes` to accept every default without a prompt.
- The daemon prunes location history, place visits and group events older than the retention window once a day, with no restart needed after changing it.
- `install.sh --start` installs, runs the setup wizard and starts the service in one command. A fresh install finishes by asking you to sign in, which is a success, not an error.
- The Alerts tab has a Delivery log showing each alert's rule, channel, kind, message text and body, time, status and error.
- An Uninstall page in the wiki with the manual service-removal commands for macOS, Linux and Windows.
- A bundled Lucide icon sprite (48 icons, ISC licensed) the dashboard loads once at startup.
- An icon picker for device and group badges: the 48 bundled icons grouped by kind, a letter of your choice, or a plain coloured dot.
- A colour picker for device and group badges: the 12 palette colours, or any colour you pick.
- One badge renderer behind the map markers, the timeline track heads and the group legend, so a device's icon and colour look the same everywhere.
- An i18n scaffold for the dashboard: `web/app/i18n.js` and the English catalog at `web/locales/en.json`, whose honesty sentences are generated from the same source the API serves. Every string the dashboard shows now comes from that catalog, so a second language can replace one file.
- A phone-width layout: under 600px the dashboard gets a bottom tab bar, the toolbar collapses behind a More button, dialogs open full screen, and every button and tick box is at least 44px to tap.
- WCAG 2.1 AA groundwork: page landmarks, a label on every form control, a visible focus ring, a focus trap and Escape-to-close on the Devices and Settings dialogs, an announced alert banner, and colour changes where text or a control border fell short of the contrast minimum.
- An accessibility scan in the browser test suite: axe-core over every tab, in both themes, at desktop and phone width.
- An alert rule can now pick any combination of Telegram, webhook, WhatsApp and Mac notifications, through a checkbox set in the rule form and a repeatable `--channel` option on `findplus alerts rules add`. Mac notifications only appear as a choice on macOS.
- Native macOS notifications for alerts. The daemon queues them and the menu bar app shows them, so an alert arrives even with no dashboard window open. While Find+ is locked, or unless you turn notification details on, the banner says only "Find+ alert", because a notification preview can appear on a locked screen.
- WhatsApp alerts, relayed through CallMeBot. The setup text says plainly that your alert text passes through a third party before it reaches WhatsApp. Set it up in the Alerts tab, which carries that text and the CallMeBot contact details, or from the terminal with `findplus alerts whatsapp set`/`clear`; the routes behind it are `PUT`/`DELETE /api/alerts/channels/whatsapp`. The phone number is shown masked and the API key is never returned.
- Alert rules can target more than one channel at once. Each channel gets its own delivery row and its own cooldown, so a notification on one never suppresses another.
- Device and group labels, icons and colours: `PATCH /api/devices/{id}`, `GET /api/icons`, `findplus devices label`/`findplus devices icons`, exports and the macOS widget all carry the new fields. A label is local only and survives every provider name refresh.
- Edit a device's label, icon and colour from the dashboard: every row in the Devices dialog has an Edit button, and the choice shows up on the device list, on every map marker, on the timeline track heads and in the macOS widget.
- A group create and edit dialog on the Groups tab: name, icon, colour, quorum, cluster radius, stale-after minutes and which tracked devices belong to the group.
- Group cards on the Groups tab, each with the group badge, its member avatars, its live presence verdict, and edit and delete buttons.

### Changed
- CI runs the accessibility scan, the icon and catalog drift check, and the Rust notification tests as three lanes of their own, so each failure names itself.
- README and wiki screenshots are regenerated at 1280x800, with a matching phone-width set at 375x812.
- The Chrome-not-found message is one sentence now shared by the terminal, the API and `/api/config`, instead of two wordings that could drift apart.
- Starting a sign-in requires the request to carry an `Origin` or `Sec-Fetch-Site` header. Browsers and the desktop app always send one; nothing else has a reason to start a sign-in.
- `PUT /api/settings` is now `PATCH /api/settings`, and its body carries the poll interval, the history retention period and whether native notifications may show details.
- The Homebrew caveats and the installer both point new installs at `findplus setup`, so every install channel gives the same first instruction.
- `findplus start` finishes a fresh sign-in in one run: it discovers devices from every provider you are signed in to, shows them, tracks them all and installs the service. Pass `--no-track-all` to discover without tracking.
- `findplus start` exits 4 when you are not signed in yet, instead of 0, and counts an Apple sign-in as being signed in.
- `install.sh` is shorter and points at a new Uninstall wiki page for the manual service-removal commands it prints. Without `--start` its last line now points at `findplus setup`.

### Fixed
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

# Changelog

All notable changes to Find+ are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `install.sh --start` installs, runs the setup wizard and starts the service in one command. A fresh install finishes by asking you to sign in, which is a success, not an error.
- The Alerts tab has a Delivery log showing each alert's rule, channel, kind, time, status and error.
- An Uninstall page in the wiki with the manual service-removal commands for macOS, Linux and Windows.
- A bundled Lucide icon sprite (48 icons, ISC licensed) the dashboard loads once at startup.
- An icon picker for device and group badges: the 48 bundled icons grouped by kind, a letter of your choice, or a plain coloured dot.
- A colour picker for device and group badges: the 12 palette colours, or any colour you pick.
- One badge renderer behind the map markers, the timeline track heads and the group legend, so a device's icon and colour look the same everywhere.
- An i18n scaffold for the dashboard: `web/app/i18n.js` and the English catalog at `web/locales/en.json`, whose honesty sentences are generated from the same source the API serves.
- Device and group labels, icons and colours: `PATCH /api/devices/{id}`, `GET /api/icons`, `findplus devices label`/`findplus devices icons`, exports and the macOS widget all carry the new fields. A label is local only and survives every provider name refresh.

### Changed
- `PUT /api/settings` is now `PATCH /api/settings`, and its body carries the poll interval, the history retention period and whether native notifications may show details.
- The Homebrew caveats and the installer both point new installs at `findplus setup`, so every install channel gives the same first instruction.
- `findplus start` finishes a fresh sign-in in one run: it discovers devices from every provider you are signed in to, shows them, tracks them all and installs the service. Pass `--no-track-all` to discover without tracking.
- `findplus start` exits 4 when you are not signed in yet, instead of 0, and counts an Apple sign-in as being signed in.
- `install.sh` is shorter and points at a new Uninstall wiki page for the manual service-removal commands it prints. Without `--start` its last line now points at `findplus setup`.

### Fixed
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
- The widget shows the device with the newest fix rather than the first by name, spells a long gap in days, and names group verdicts the way the dashboard does.
- The lock screen states that locking does not encrypt the database, which until now was only visible in Settings, behind the lock.
- The Delivery log shows times in your local timezone and says why an alert was skipped.
- The group presence lists say which members are together and which are away.
- The installer pins the released version, tells you when `~/.local/bin` is not on your PATH, names the package to install when `venv` is missing, and rebuilds a virtualenv whose Python has gone.
- The macOS app bundle no longer carries the repository's editor configuration files.
- The Homebrew formula points at the release the tag actually published.

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

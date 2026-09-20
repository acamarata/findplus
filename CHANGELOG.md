# Changelog

All notable changes to Find+ are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The Alerts tab has a Delivery log showing each alert's rule, channel, kind, time, status and error.
- An Uninstall page in the wiki with the manual service-removal commands for macOS, Linux and Windows.

### Changed
- `install.sh` is shorter and points at a new Uninstall wiki page for the manual service-removal commands it prints.

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

# Changelog

All notable changes to Find+ are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

- E1: api, cli, service and app.js split into packages; INVARIANTS.md maps every invariant to a test
- E2: Settings owns every `~/.findplus` path (`ensure_state_dir()`, computed path properties)
- E2: Alembic migrations bundled into `findplus.db.migrations` (package-relative, wheel-safe)
- E2: GoogleFindMyTools vendored into the wheel via hatch `force-include`
- E2: daemon runtime file I/O; `/api/health` gains `app`/`version`/`pid`
- E2: `findplus config get|set|unset|list|path` and `findplus db upgrade|current|path` added
- E2: wheel-install smoke test proves the packaging foundation end-to-end
- E7: user-level service management (install/start/stop/status/uninstall, watchdog, SIGTERM handling)
- E3: provider abstraction (LocationProvider protocol, registry, devices.provider column)
- E11: Apple Find My provider as an optional extra (`pip install 'findplus[apple]'`).
  Register accessories via `findplus apple add-accessory`; authenticate via
  `findplus auth --provider apple-find-my`; polls alongside Find Hub automatically.
- Places and geofences: save circular geofence areas, track ENTER/EXIT events per device with
  configurable hysteresis (`enter_confirmations`, `exit_confirmations`), and query current presence.
  Pruning or clearing location history also removes the place events anchored to the deleted
  observations.
- `findplus places` CLI subcommand: list, add, edit, remove, events.
- `GET/POST /api/places`, `PUT/DELETE /api/places/{id}`, `GET /api/places/events`,
  `GET /api/places/presence` API routes.
- Alembic migration 0004 adds `places`, `place_events`, `place_states` tables.
- E5: device groups with partial-presence detection and quorum-based group crossing events
- E12: PyPI packaging, curl installer and Homebrew formula

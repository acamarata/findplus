# Architecture

## The decision: reuse GoogleFindMyTools, do not fork find-hub-tracker

Two upstream projects were audited before any code was written.

### `leonboe1/GoogleFindMyTools` — adopted as a vendored dependency

GPL-3.0, 1,171 stars, actively maintained, pinned here at commit
`d46e9528578015b51d3b84dd91bf8f16e9ab850f` (2026-02-07) under `cli/vendor/GoogleFindMyTools/`.

This project solves the genuinely hard problem: Google's Nova/Spot protocol, the
FMDN end-to-end-encryption scheme, owner-key retrieval, and the Android
authentication chain. None of that is reimplemented here. Reproducing
reverse-engineered cryptography would be both wasteful and a reliability
liability.

### `karlmarx/find-hub-tracker` — audited and rejected

The brief suggested this project "already solves the difficult Find Hub /
authentication / history portion." It does not. It is a thin consumer of
GoogleFindMyTools that adds a Discord bot. The audit found:

| Finding | Evidence |
|---|---|
| **No license file** | All rights reserved; not legally forkable or redistributable. |
| **Stdout scraping** | `google_fmd.py` wraps `redirect_stdout` around upstream's printing function and regex-parses `"Latitude:"` lines back into floats. Its own docstring calls this "fragile". |
| **Loses observations** | Find Hub returns a *batch* of timestamped reports per request. The line parser overwrites `lat`/`lng` on each match, so only the final report survives. |
| **No deduplication** | `poller.py` calls `db.store_location(loc)` unconditionally every cycle. Its 100 m `_has_moved_significantly` check gates only *Discord posting*, not storage — so the database accumulates a fake point every five minutes. |
| **Zero tests** | No test files exist in the repository. |
| **Wrong shape** | Postgres/Docker/Discord-first. Its migrations use `BIGSERIAL`, `TIMESTAMPTZ` and `NOW()`, which do not run on SQLite as written. No API, no map, no UI. |
| **Maturity** | 7 commits, 5 stars, created 2026-03-30. Ships its own `PROMPT.md` and `SPEC.md`: an AI-scaffolded spec build. |

Everything above the Find Hub protocol is therefore written here.

## The one adaptation that matters

Upstream's `get_location_data_for_device()` **prints** results and returns `None`.
Rather than scrape that output, `findhub/client.py` calls the same upstream
primitives — `retrieve_identity_key`, `is_mcu_tracker`,
`foreign_tracker_cryptor.decrypt`, `cloud_key_decryptor.decrypt_aes_gcm`, and the
protobuf decoders — and returns typed `RawObservation` values.

No cryptographic or protocol code is modified. The print loop is replaced by a
return. The payoff is direct: **every report in the batch is kept**, so one poll
often yields several distinct historical observations rather than one.

Two upstream robustness defects are contained rather than inherited:

1. `decrypt_locations.retrieve_identity_key()` calls `exit(1)` on an owner-key
   version mismatch. `SystemExit` is caught and re-raised as `DecryptionError`,
   so the daemon survives.
2. `location_request.get_location_data_for_device()` busy-waits
   `while result is None: time.sleep(0.1)` with no timeout. This client uses a
   `threading.Event` with a hard `POLL_TIMEOUT_SECONDS` bound.

## Component map

```
 Google Find Hub  ──(Nova API request)──▶  Google
        ▲                                     │
        │                                (FCM push)
        │                                     ▼
 cli/vendor/GoogleFindMyTools  ◀── auth, crypto, protobuf
        ▲
        │  typed RawObservation[]
 findhub/client.py  ── structured adapter (the only Google-aware module)
        │
        ▼
 poller.py  ── schedule, backoff, failure recording
        │
        ▼
 ingest.py  ── deduplication ─────▶  SQLite (SQLAlchemy 2.0 + Alembic)
                                         │
                       ┌─────────────────┴──────────────────┐
                       ▼                                    ▼
              timeline.py                            exporters.py
         day grouping, gaps, stats                CSV / JSON / GPX / KML
                       │                                    │
                       └────────────┬───────────────────────┘
                                    ▼
                               api.py (FastAPI, 127.0.0.1 only)
                                    │
                                    ▼
                    web/static  ── Leaflet + OpenStreetMap, vanilla JS
```

`cli.py` drives all of it; `service.py` handles launchd/systemd/Task Scheduler.

## Multi-device model

`devices.is_tracked` drives polling; any number may be set. The poller walks the
tracked set **sequentially with a stagger** rather than firing N concurrent
requests, and records one `poll_runs` row per device so a single tracker failing
is visible without masking the others. A cycle is "ok" if at least one device
reported.

One case is handled specially: "no devices tracked" sets `CycleOutcome.config_error`
and deliberately does **not** escalate the exponential backoff. It is a
configuration state, not a Google failure — escalating would leave a freshly
installed daemon asleep for an hour at exactly the moment the user finishes
selecting their trackers.

`timeline.multi_day_timeline()` returns one **independent** `DayTimeline` per
device. Merging is not offered, because `meters_from_previous` and
`seconds_since_previous` are only meaningful within a single tracker; an
interleaved list would report distances between unrelated objects. The UI assigns
each device a colour and renders a separate polyline, marker set and statistics
block.

## Data model

Four tables, migrated by Alembic (revisions `0001`, `0002`).

**`location_observations`** is the core. Its design encodes three requirements:

- **Coordinates are stored as integer 1e-7 degrees** (`latitude_e7`), the native
  wire precision Google returns. Integers make deduplication exact and immune to
  float comparison drift. Float degrees are derived properties.
- **`observed_at` and `first_fetched_at` are separate columns.** When Find Hub saw
  the tag and when this computer asked are unrelated facts; the timeline uses
  `observed_at`, and the UI shows both.
- **`UNIQUE (device_id, observed_at, latitude_e7, longitude_e7)`** is the
  deduplication contract, enforced by the database and not only by code. When
  Google returns the same last-known fix again, `times_returned` and
  `last_fetched_at` are updated and no new point is created.

`poll_runs` records health separately, so "we polled 200 times today and the tag
was seen 6 times" is expressible without polluting the location history.

## Timestamps and timezones

All timestamps are stored as **naive UTC** through a `UtcDateTime` `TypeDecorator`
that re-attaches `timezone.utc` on load and **raises on any naive input**, so a
timezone-less datetime can never silently corrupt day grouping.

Local time is a presentation concern. Day boundaries are computed as
`[local midnight, next local midnight)` using the machine's IANA zone, never
`start + 24h` — which is why a spring-forward day correctly spans 23 hours and a
fall-back day 25. Both are covered by tests.

## App lock

The lock is enforced by a FastAPI middleware, not by the front end. Every path
under `/api/` except `/api/health`, `/api/lock/status` and `/api/lock/unlock`
returns `401` while locked. This is the whole point: a UI-only lock would leave
the history readable with `curl` from the same machine.

- PIN → salted **scrypt** (`n=2**15, r=8, p=1`, ~46 ms per verification).
  OpenSSL caps `maxmem` at exactly 32 MiB, which this configuration needs, so the
  limit is raised explicitly rather than weakening the cost parameters.
- Verification is constant-time and rate-limited: 5 failures trigger a 60-second
  lockout that also blocks the correct PIN, because a 4-digit PIN is otherwise
  trivially brute-forced over a local API.
- Sessions are **in-memory only** — a service restart or reboot re-locks the app,
  which is the desired default. The token is an `HttpOnly`, `SameSite=Strict`
  session cookie.
- Changing the PIN revokes every session, then immediately re-issues one to the
  calling browser. Other devices are signed out; the person who just set the PIN
  is not locked out of the window they set it in.
- Recovery is `findplus reset-lock`, which requires local filesystem access —
  the same access that would let someone read the SQLite file anyway, so the
  recovery path adds no exposure that did not already exist.

**Threat model, stated plainly:** this is deterrence against another person using
this computer. It is not encryption at rest. `data/findplus.sqlite` is a
plain file readable by this user account. FileVault is the answer to the other
problem, and the UI says so rather than implying more than it delivers.

## Keeping the service alive

Two independent user-level jobs, because they cover different failures:

- `KeepAlive` on the main job restarts a process that **died**.
- A separate watchdog job (`StartInterval` 300 s) restarts a process that is
  **alive but not answering** — something `KeepAlive` cannot detect.

The watchdog treats `401` as healthy, so turning on the app lock does not send it
into a restart loop. It never raises: it runs unattended on a timer, where a
crash would be silent and permanent.

## Deliberate non-goals

- **No interpolation.** A gap in detections is drawn as a gap. Intermediate
  positions are never invented.
- **No claim of a travelled route.** Distances are geodesic (Haversine) hops
  between observations, labelled "Approximate distance between observed
  locations" everywhere they appear, including in exports.
- **No movement filtering at write time.** `MOVEMENT_THRESHOLD_METERS` annotates
  observations at read time with an `is_movement` flag. Raw data is never
  discarded.
- **No microservices.** This is one process serving one user on one machine.

## Privacy and network posture

- Binds to `127.0.0.1`. `Settings` raises on any other host unless
  `FINDPLUS_ALLOW_PUBLIC_BIND=1` is set explicitly.
- Leaflet is vendored locally; the page loads no third-party scripts. A test
  asserts every `<script src>` is same-origin.
- No analytics, telemetry, cookies, or cloud database.
- **One unavoidable external request:** map tiles come from
  `tile.openstreetmap.org`, which therefore sees which tile coordinates are being
  viewed. This is stated in the UI footer. Point the tile URL at a local tile
  server or an offline `.mbtiles` source to eliminate it.
- Logging redacts sensitive keys by name and scrubs token-shaped strings from
  free text. Tests cover both paths.

## Authentication material

`findplus auth` opens real Chrome at Google's own
`accounts.google.com/EmbeddedSetup` and waits for the `oauth_token` cookie Google
sets after a normal login, including 2FA. Nothing bypasses Google's security.

`gpsoauth` then exchanges that cookie for a long-lived AAS token. The result —
account email, AAS token, device-manager token, FCM credentials, and the E2EE
owner key — is written to a single `secrets.json`.

Upstream resolves that file relative to its own package directory. `bootstrap.py`
rebinds `Auth.token_cache._get_secrets_file` so it lands in
`~/.findplus/` (mode `0700`, file mode `0600`) instead of inside `vendor/`.
That monkeypatch replaces a path resolver only; it does not touch key derivation,
decryption, or request signing.

**Your Google password is never seen, stored, or transmitted by this application.**

## Dependency notes

`frida` appears in GoogleFindMyTools' `requirements.txt` but is imported nowhere
in its codebase (verified by grep). Frida is a dynamic binary instrumentation
toolkit; it is deliberately excluded from this project's dependencies.

`undetected-chromedriver` is required by upstream's `chrome_driver.py`. It patches
a downloaded chromedriver to avoid bot-detection fingerprinting. Note that
upstream's `create_driver()` runs `os.system("pkill -f chrome")` before launching,
which closes any Chrome windows you have open. The `auth` command warns about this
before proceeding.

## Licensing

GoogleFindMyTools is GPL-3.0. This project links it as a library, so this project
is licensed **GPL-3.0-or-later**. Upstream attribution and its `LICENSE` are
preserved under `cli/vendor/GoogleFindMyTools/`.

## Extension point: geofences (not in v1)

Alert zones were designed for but not built. The intended shape: a `zones` table
(`name`, `center_lat_e7`, `center_lon_e7`, `radius_meters`) plus a `zone_events`
table, with evaluation running in `ingest.py` immediately after a new observation
is inserted — the single point where new sightings are known to be genuinely new.
Because deduplication already guarantees "new row means new sighting", enter/exit
detection does not need to re-filter repeats.

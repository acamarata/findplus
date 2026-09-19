# CONTEXT — everything behind Find+ (FindPlus)

This is the full record of how Find+ came to exist: the original ask, the research
that was actually performed, every decision and its reasoning, every bug found, and
the exact state of the code at handoff. `PROMPT.md` is the instruction set;
`PLAN.md` is the ticket list; this file is the evidence behind both. Before you
change any invariant listed in `PROMPT.md` §2 or any decision in `PROMPT.md` §3,
find the reason here first.

- **Session 1 (build):** 2026-09-18 → 2026-09-19, machine MM4 (Mac mini M4, macOS
  27.0, arm64), Python 3.12.13 in-venv. Transcript (Claude Code JSONL):
  `~/.claude/projects/-Users-admin-Downloads/5fbb5248-76e4-5941-a5b8-d06ef3322bdd.jsonl`.
- **Session 2 (planning, copy, rename):** 2026-09-19, same machine. Produced the
  first plan under the working name "Waypost", then copied and renamed the code to
  `findplus` after the owner chose the final name. Details in §12.
- **Code at handoff:** `/Volumes/UG/Sites/acamarata/findplus` (renamed in session 3; see §12h;
  directory to `findplus` before session 3), 6 commits, clean tree, 262 tests passing,
  ruff clean. The original `/Users/admin/Developer/bike-tracker` still exists and is
  deleted by session 3 (`PROMPT.md` §1).

---

## 1. The original request, in the owner's own framing

The owner owns a **Moto Tag 2** (Google Find Hub tracker) attached to a child's
**bicycle**. Google Find Hub shows only the *latest* position. He wanted this computer
to poll it periodically, build its own history database, and show a Google-Maps-
Timeline-style day view:

```
8:03 AM — location A
8:18 AM — location B
8:37 AM — location C
9:02 AM — location D
```

Explicit requirements, all implemented unless noted:

| Requirement | State |
|---|---|
| Research `leonboe1/GoogleFindMyTools` and `karlmarx/find-hub-tracker` first; favour reuse over rebuilding Google's reverse-engineered protocol | done, §2 |
| Do not blindly execute GitHub scripts; inspect deps and explain security-sensitive components | done, §3 |
| Architecture: Find Hub integration → poller → SQLite → local REST API → browser UI → background service | done |
| Bind to `127.0.0.1` only, never LAN/Internet | done, enforced in `Settings` |
| Never ask for / store the Google password; use the normal interactive Chrome flow; keep tokens out of git; an `auth` command to re-auth | done |
| Enumerate Find Hub devices, let the user select, store only the non-secret id, allow changing later | done (later widened to multi-select) |
| Poll every 5 min by default; never faster without strong evidence; configurable | done, floor enforced in code |
| Capture device id/name, lat, lon, observation time, retrieval time, accuracy, source, battery, raw metadata | done (battery is null; upstream does not expose it for tags) |
| **Differentiate `OBSERVED_AT` from `FETCHED_AT`**; timeline uses `OBSERVED_AT` | done, separate columns, both shown |
| Deduplicate; no fake movement point every 5 min; one canonical observation; record poll health separately | done, DB unique constraint + `poll_runs` |
| SQLite, no Docker; tables `devices`, `location_observations`, `poll_runs`, `settings`; indexes; **migrations, not manual schema edits**; gitignored DB | done, Alembic `0001`, `0002` |
| Leaflet + OpenStreetMap (no paid map API) | done, Leaflet vendored |
| Main screen: selected tag, latest location, last-seen, how-long-ago, last poll, service status, observations today | done |
| Date picker; numbered time-ordered markers; connecting polyline; fit bounds; click → details | done |
| **Never imply the straight line is the real road**; label it "Observed path — actual route between detections may differ." | done, verbatim |
| Chronological timeline beside the map; click item → pan to marker | done |
| `MOVEMENT_THRESHOLD_METERS=25`; distinguish raw vs meaningful movement; **never discard raw data** | done, read-time `is_movement` flag |
| Daily stats: first, last, unique count, approximate distance, longest gap, time span; Haversine | done |
| Detection gaps ("NO NEW DETECTIONS FOR 47 MINUTES"); default 20 min; **no interpolation** | done |
| "Latest Location" with observed time, retrieved time, age | done |
| Dashboard auto-refresh every 30–60 s against the LOCAL API only | done, 45 s default |
| Exports CSV / JSON / GPX / KML; day, range, or all | done |
| `RETENTION_DAYS=0` = unlimited; safe delete-before command; never silently delete | done |
| Autostart: detect OS, user-level service, show exactly what will be installed first | done, launchd/systemd/schtasks |
| CLI: start, stop, status, auth, devices, poll-now, open, export, doctor | done, plus more |
| Reliability: offline, Google down, API changes, auth expiry, decryption errors, duplicates, missing location, malformed data, machine asleep; never crash; backoff; **never fabricate a location** | done |
| Rotating logs; never log passwords/cookies/tokens/keys | done, redaction processor |
| Privacy: local only, no analytics/telemetry/cloud/ads/third-party scripts; document the tile-provider exception | done |
| Architect for future geofences | **now required, §8c** |
| UI note that a Moto Tag is not a cellular GPS tracker (owner's exact wording) | done, verbatim |
| Tests: dedup, timestamps, timezones, Haversine, movement threshold, daily grouping, gaps, migrations, exports; never hit the real account | done, 262 tests |
| Timezone: machine default, UTC internally, local for UI, DST-safe | done, 23 h / 25 h days tested |
| Type hints, clean modules, structured logging, migrations, tests, lint, config, README, architecture docs; no needless abstraction | done |
| Stack: Python 3.12+, FastAPI, SQLite, SQLAlchemy, Alembic, GoogleFindMyTools, Leaflet, vanilla JS; no React/Node unless it materially helps | followed exactly |

---

## 2. The upstream research — findings in full

### `leonboe1/GoogleFindMyTools` — adopted

GPL-3.0 · 1,171 stars · Python · created 2024-11-06 · last push 2026-05-05. Vendored
at pinned commit **`d46e9528578015b51d3b84dd91bf8f16e9ab850f`** (2026-02-07) under
`vendor/GoogleFindMyTools/`, with `ESP32Firmware/`, `ZephyrFirmware/`, `.github/` and
`.git/` stripped. Its `LICENSE` is kept.

It solves the genuinely hard problem and must not be reimplemented:

- `Auth/auth_flow.py` drives Chrome to `accounts.google.com/EmbeddedSetup` and waits
  for the `oauth_token` cookie Google sets after a normal login.
- `Auth/aas_token_retrieval.py`: `gpsoauth.exchange_token()` → long-lived AAS token.
- `Auth/fcm_receiver.py` registers with FCM and holds a push connection. **Location
  responses arrive asynchronously over FCM push, not as an HTTP reply.**
- `NovaApi/nova_request.py` POSTs protobuf to `https://android.googleapis.com/nova/<scope>`.
- `NovaApi/ExecuteAction/LocateTracker/decrypt_locations.py`: E2EE decryption.

### `karlmarx/find-hub-tracker` — rejected

No license · 5 stars · Python · 7 commits. The owner's brief said it "already appears
to" solve the hard part and suggested forking it. That premise was wrong:

| Finding | Evidence |
|---|---|
| **No LICENSE file** | All rights reserved. Not legally forkable. |
| **Stdout scraping** | `google_fmd.py` wraps `redirect_stdout()` around upstream's printing function and parses `"Latitude:"` lines. Its own docstring calls it fragile. |
| **Silently drops observations** | Only the last report of each batch survives its line parser. |
| **No deduplication** | `poller.py` calls `store_location()` unconditionally every cycle. This is the fake-movement bug we exist to avoid. |
| **Zero tests** | |
| **Wrong shape** | Postgres/Docker/Discord-first; SQL uses `BIGSERIAL`, `TIMESTAMPTZ`, `NOW()`; no API, no map, no UI. |

Do not revisit this decision.

### The structured-adapter adaptation

Upstream's `get_location_data_for_device()` prints results and returns `None`.
`src/findplus/findhub/client.py` therefore calls upstream's own primitives
(`retrieve_identity_key`, `is_mcu_tracker`, `foreign_tracker_cryptor.decrypt`,
`cloud_key_decryptor.decrypt_aes_gcm`, the protobuf decoders) and returns typed
`RawObservation` objects. **No cryptographic or protocol code is modified.** Every
report in the batch is retained. A test builds real `DeviceUpdate_pb2.Location`
protobufs and stubs only the crypto boundary.

Two upstream defects are contained here rather than inherited:

1. `retrieve_identity_key()` calls `exit(1)` on an owner-key version mismatch → caught
   as `SystemExit`, re-raised as `DecryptionError`; the daemon survives.
2. `location_request` busy-waits `while result is None` → replaced with
   `threading.Event` + `POLL_TIMEOUT_SECONDS`.

---

## 3. Security-sensitive components (disclosed to the owner; keep disclosing)

1. **`undetected-chromedriver`** (3.5.5, last released 2023) patches a downloaded
   chromedriver to evade bot-detection fingerprinting and drives real Chrome to
   Google's genuine provisioning endpoint. Nothing bypasses Google security; 2FA runs
   normally. **Side effect:** upstream's `create_driver()` runs
   `os.system("pkill -f chrome")` and closes every open Chrome window. The `auth`
   command warns first. Keep the warning.
2. **`frida`** appears in upstream's `requirements.txt` but is imported nowhere. It is
   deliberately excluded from our dependencies. Do not add it back.
3. **`gpsoauth`** exchanges the cookie for a long-lived AAS token, effectively
   account-level Android credentials. Highest-value secret here.
4. **Stored auth material**, one file: account email, AAS token, ADM token, FCM
   credentials + android id, E2EE owner key. `findhub/bootstrap.py` rebinds
   `Auth.token_cache._get_secrets_file` so it lands in `~/.findplus/secrets.json`
   at `0600` inside a `0700` directory. That monkeypatch replaces a path resolver only.

---

## 4. Design decisions and the reasoning behind them

- **Integer 1e-7 degrees** rather than floats: Google's native wire precision; exact
  dedup, no float drift.
- **Dedup identity = `(device_id, observed_at, latitude_e7, longitude_e7)`** with a
  database-level unique constraint. Verified live: five consecutive polls returning the
  same fix inserted 0 rows each time.
- **`poll_runs` is separate from location history** so "we polled 200 times today and
  the tag was seen 6 times" is expressible.
- **`UtcDateTime` raises on naive datetimes.** Better to fail loudly than corrupt day
  grouping.
- **Day bounds = local midnight → next local midnight.** 2026-03-08 is 23 h,
  2026-11-01 is 25 h in `America/New_York`, tested.
- **Timelines are never merged across devices.** A fixture with two devices ~350 km
  apart asserts no within-track hop exceeds 50 km.
- **Sequential polling with a 10 s stagger.** N devices cost N requests per cycle; the
  effective rate is shown in UI and CLI.
- **"No devices tracked" does not escalate backoff** (`CycleOutcome.config_error`).
- **App lock enforced in middleware**, not the front end.
- **Sessions are in-memory only**, so a restart re-locks.
- **Changing the PIN revokes all sessions then re-issues one to the caller.**
- **`scrypt` `maxmem` raised to 64 MiB** (n=2**15, r=8 needs exactly OpenSSL's default
  cap); cost parameters were not weakened. ~46 ms per verification.
- **Brute-force lockout blocks the correct PIN too.**
- **Watchdog treats `401` as healthy.**
- **Leaflet vendored locally**; a test asserts every `<script src>` is same-origin.

---

## 5. Bugs found during the build — all real, all fixed

1. **Device dialog rendered open on every page load.** `.modal { display: flex }` beat
   `.hidden` at equal specificity. Fixed with `.modal.hidden { display: none }`.
   *Found by screenshotting the running app.*
2. **Coordinates remained in the DOM after locking.** The API returned 401 correctly
   while the page still held the data. Fixed with `purgeRenderedData()`. *Found by a
   Playwright assertion.*
3. **Starting locked broke the session permanently.** `main()` returned early at the
   lock screen so `loadConfig()` never ran. Fixed with a shared `bootDashboard()`.
4. **`--track-all` tracked zero devices** with an empty local table. *The owner hit
   this.*
5. **Setting a PIN locked you out of your own browser.**
6. **Backoff escalated while unconfigured.**
7. **`local_zone()` returned UTC** because `tzlocal` was absent. Added `tzlocal` and a
   `/etc/localtime` fallback.
8. **`favicon.ico` 404**; added `icon.svg`.

**Lesson: run the app and screenshot it.** Three of these were invisible to the
Python suite.

---

## 6. Verified-working evidence (live runs)

- Seeded demo day rendered exactly as specified, including jitter suppression and gap
  banners (7 points, two gaps, two jitter annotations).
- Three devices tracked simultaneously: `~36.0 Google req/hr`, three independent
  coloured tracks with separate statistics.
- App lock: `/api/status`, `/api/timeline`, `/api/export` returned **401** with zero
  coordinate leakage; 5 wrong PINs → **429** that also blocked the correct PIN.
- All four exports validated (GPX/KML parse as XML; 7 trackpoints with `<time>`).
- The watchdog validated itself unprompted during a service restart.
- 12 Playwright browser tests green against real Chrome.

---

## 7. What the owner has NOT done yet

**Google authentication was never completed.** His attempt failed because a
copy-pasted `#` comment was parsed as a CLI argument:

```
Error: Got unexpected extra arguments (# ⚠️ closes your open Chrome windows)
```

So the database is empty, no real Find Hub device has ever been contacted, and the
decryption path has never run against live data. Everything was verified with seeded
fixtures and real protobufs. Expect to debug the live path on first real auth.

The launchd jobs installed during session 1 (`com.acamarata.bike-tracker` and
`.watchdog`) were stopped, booted out and their plists deleted on 2026-09-19. Session 2
re-verified: nothing loaded, no plist, nothing listening on 8477 or 8647.

---

## 8. The expanded scope — the owner's asks, verbatim in substance

### 8a. Rename and go FOSS

> "Don't call this app 'Bike Tracker' but something like 'Hub+' or maybe we need to
> move this to acamarata/hubplus — Because we want this to be our Google FindMy Hub,
> plus more features... or FindMyPlus FMP? — you help with the name"

> "What about FindPlus and it works with Apple and Google both environments? Though
> Waypost is kinda good too and if completely open on different platforms then good"

Name research performed 2026-09-19 (all checks live):

| Candidate | PyPI | github.com/acamarata | Verdict |
|---|---|---|---|
| `tagalong`, `lodestar`, `whereabouts` | taken | free | out |
| `hubplus` | free | free | rejected: ties us to Google's current branding ("Find My Device" → "Find Hub" in 2025) and excludes non-Google backends |
| `findmyplus` | free | free | rejected: "Find My" is Apple's trademark; takedown risk, higher because we query Apple's network |
| `waypost` | free | free | proposed by session 2's first plan; vendor-neutral |
| `findplus` | free | free | **chosen by the owner, 2026-09-19** |

**Final decision (owner):** display name **Find+**, identifier **FindPlus /
`findplus`**, repo `acamarata/findplus`. Reasoning: the product covers Apple and
Google, the name says what it does, and dropping the distinctive "My" removes the
direct trademark collision. Residual guidance: never style it "Find My+"; no Apple or
Google logos; a "not affiliated" line in the README.

### 8b. Multi-platform (Apple and Google)

Research performed 2026-09-19:

| Project | Stars | License | Language | Last push |
|---|---|---|---|---|
| `malmeloo/FindMy.py` | 3,266 | MIT | Python | 2026-09-15 |
| `seemoo-lab/openhaystack` | 13,562 | AGPL-3.0 | Swift | 2026-08-17 |
| `dchristl/macless-haystack` | 2,185 | AGPL-3.0 | Dart | 2026-03-15 |
| `leonboe1/GoogleFindMyTools` | 1,171 | GPL-3.0 | Python | 2026-05-05 |

FindMy.py is the right Apple-side dependency: Python, MIT, active. Session 2 checked
the PyPI release: **0.10.2**, `requires-python >=3.10,<3.15`, dependencies `srp`,
`cryptography`, `beautifulsoup4`, `aiohttp`, `bleak`, `typing-extensions`,
`anisette`. Its package exports `LocalAnisetteProvider` and `RemoteAnisetteProvider`,
`AppleAccount`/`AsyncAppleAccount`, `FindMyAccessory`, SMS and trusted-device
second-factor helpers. Its README claims official accessories (AirTags, iDevices) and
OpenHaystack tags.

Honesty constraints for Apple support: keys you hold; DIY/OpenHaystack tags work well;
genuine AirTags need accessory keys extracted from pairing data, which most users
cannot do; Apple ID auth needs an Anisette provider (a local one is bundled now);
never vendor AGPL code (OpenHaystack, macless-haystack).

### 8c. Places and geofencing with alerts

> "We need to be able to set locations like Home, Grandma's House, School, Store,
> etc... and do geofencing and alerts when a child goes certain places (alerts can be
> a simple settings option where user sets up Whatsapp or Telegram bot + your owner id
> type of things — like if I used our @camarata_bot + my Telegram ID... easier if we
> tell people to enter phone numbers or usernames if hard for them to find ID's"

Usability requirement: **do not make people hunt for a Telegram chat id.** Build the
capture helper.

### 8d. Tracker groups with partial-presence logic

> "We need to be able to group trackers like what if someone had a tracker in their
> child's shoes, bike, backpack so those all belong to one group for that child...
> also note that if a Child's group they could leave their backpack home but be out
> with bike and shoes tracked or only one... so we need some smart logic to know when
> the child left with all, some, or one tracker."

The hard part is **stale ≠ at home**. A tag with no recent fix is `stale`, not "left
behind". Conflating them would produce confidently wrong statements about a child's
location, the worst possible failure for this app.

### 8e. Distribution and the macOS app

> "We could release this as a macOS app via bundle and gh release with a dmg or
> whatever or as a cli that people would 'curl bash' to install (or homebrew) and have
> the local webapp at hubplus.local or whatever? Both if easy..."

> "git clone / appname auth / appname start — or minimal steps possible"

> "I would like full CLI, API, MCP compatibility if someone is asking an AI agent to
> run this on their computer"

> "people could also download the dmg, install app... then the UI is a Tauri app with
> the same db, daemon, etc. and it could run in macOS top menu bar and then opening
> the app itself from /Applications gives the window full UI... where clicking the top
> menubar icon would give a drop down with maybe first item as a colored dot and status
> and then any other quick options and then 'Open App'"

Addresses floated: `<name>.local`, `<name>.localhost`, `localhost:8647`. Session 2
decided on `localhost:8647` only (§12).

### 8f. Overall instruction

> "I want you to design, build, test, and document a complete FOSS application in
> acamarata/appname with this and make it so anyone and everyone can use with the
> least steps possible."

> "Develop however best to get it all done FAST!!!"

And, on 2026-09-19 after the first plan:

> "there should be no phases yet but we could build this as P1 for FindPlus"

> "The thing that is very important is that we get absolutely everything planned out
> to full details, and nothing is missing."

---

## 9. State of the code at handoff (after session 2)

```
/Volumes/UG/Sites/acamarata/findplus      (renamed 2026-09-19; the session runs here)
  6 commits, clean tree (PROMPT.md, CONTEXT.md, PLAN.md untracked, to move to .github/docs/ in E1-T2)
  .claude/ and .opencode/ present (gitignored): phase P1 forged, see §12h
  262 tests passing · ruff check clean · ruff format clean · node --check clean
  7,324 lines of Python across 43 files · 24 API routes · 16 CLI commands
  Alembic revisions 0001, 0002
  Package findplus, version 1.0.0.dev0, CLI findplus, port 8647, state dir ~/.findplus
```

Commit history:

```
a6dd275  chore: rename bike-tracker to findplus
32e4f6c  Lint cleanup
26ddf26  Purge rendered coordinates on lock; add browser tests; fix --track-all
437e573  Add app lock, settings, themes, history deletion and a watchdog
ba536a3  Track any number of Find Hub devices, with per-device timelines
68dd2d6  bike-tracker v1.0.0: local Find Hub location history
```

The rename commit touched 59 files (284 insertions, 284 deletions): package directory
`git mv`, imports, `pyproject.toml` (name, script, version, description), env prefix
`FINDPLUS_`, state dir `~/.findplus`, DB file name `findplus.sqlite`, export file
prefix, service labels and unit names, Task Scheduler name `FindPlus`, session cookie
`findplus_session`, default port 8647, UI title "Find+", `icon.svg` aria-label, README
and ARCHITECTURE command names, tests. The old venv was excluded from the copy;
`data/` (an empty seeded DB) was excluded too.

Dependencies deliberately chosen: FastAPI, uvicorn, SQLAlchemy 2.0, Alembic,
pydantic-settings, click, structlog, tzlocal, plus GoogleFindMyTools' runtime deps
minus frida. Dev: pytest, ruff, playwright, freezegun. Installed versions in the
session-2 venv: fastapi 0.141.1, uvicorn 0.53.0, SQLAlchemy 2.0.54, alembic 1.20.0,
protobuf 7.36.2, gpsoauth 2.0.0, selenium 4.49.0, undetected-chromedriver 3.5.5,
pytest 9.1.1, ruff 0.16.8, playwright 1.63.0.

---

## 10. Standing constraints from the owner's global instructions

- **No AI attribution** anywhere in version-controlled output. A global pre-commit
  hook at `~/.git-hooks/pre-commit` enforces it.
- **Clean repo root:** `.gitignore`, `README.md`, `LICENSE`, `CHANGELOG.md`,
  `pyproject.toml`, `install.sh` plus allowed directories. Human docs in
  `.github/wiki/` (public) or `.github/docs/` (private working docs).
- **pnpm only** for any JS/TS tooling. Never npm/yarn/bun. (The plan avoids a JS
  build entirely.)
- **Human tone in docs:** no em-dash connectors, no "dive into", "seamlessly",
  "robust", "leverage", "moreover". Short sentences, active verbs.
- **Never commit** `.env`, `secrets.json`, `*.pem`, `*.key`, or the SQLite file.
- **Version bumps and publishing** to public registries need explicit approval.
- **Never pay GitHub** for Actions; a release must be reproducible locally.
- **Vercel is not involved** (no web deploy; everything is local).
- Files over 300 lines and functions over 50 lines violate the engineering standard;
  the plan splits the three offenders.

---

## 11. How to use this file

`PROMPT.md` tells you what to do. `PLAN.md` tells you in what order and with which
tests. This file tells you why, and records what was already tried, measured and
rejected. Before changing any of the twelve invariants or the twenty decisions in
`PROMPT.md`, find the reasoning here; every one exists because of a specific failure
mode, and most were paid for with a real bug.

---

## 12. Session 2 (2026-09-19): planning findings and the copy/rename

### 12a. What was verified live (not assumed)

| Item | Result |
|---|---|
| Old launchd jobs | `launchctl list \| grep -i bike` empty; no plist in `~/Library/LaunchAgents` |
| Old state dir | `~/.bike-tracker/` contains only `logs/` |
| Ports 8477 / 8647 | nothing listening |
| Python | Homebrew 3.12 and 3.13 present; system `python3` is 3.14.7 (not used) |
| Rust / Tauri | cargo 1.98.0, `tauri-cli 2.11.4`; crates.io: tauri 2.11.5, tauri-plugin-positioner 2.3.4, tauri-plugin-shell 2.3.6, tauri-plugin-single-instance 2.4.4 |
| Node / pnpm | node 24.6.0 and pnpm present; not needed by the plan |
| Signing | Xcode installed; `security find-identity -v -p codesigning` shows one valid **Developer ID Application: Aric Camarata (5398R82926)** |
| Vault (`~/.claude/vault.env`, names only) | `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_SIGNING_IDENTITY`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`, `APPLE_API_KEY_P8_BASE64`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_CERTIFICATE_PASSWORD`. **Absent:** a `.p12` export of the certificate, any PyPI token, any Twilio/Meta credential. Telegram bot tokens exist for the owner's own testing only and never go into code or fixtures. |
| GitHub | `gh` authenticated as `acamarata`; `acamarata/findplus`, `acamarata/waypost` and `acamarata/homebrew-tap` do not exist |
| PyPI | `findplus` and `waypost` free (404). `mcp` 2.2.0 (MIT). `zeroconf` 0.151.3 (**LGPL-2.1-or-later**). `pyinstaller` 6.22.3 (GPL-2 with bootloader exception; build tool only, never a runtime dependency). `findmy` 0.10.2 (see §8b). |
| Baseline suite in the new location | 262 passed before the rename, 262 passed after; ruff and `node --check` clean both times |

### 12b. Packaging and structure findings (the reasons behind PROMPT.md §3)

- `pyproject.toml` `[tool.hatch.build.targets.wheel] packages = ["src/findplus"]`
  ships only the package. `migrations/` (with `alembic.ini` at the root) and
  `vendor/GoogleFindMyTools/` are outside it. `db/migrate.py` and
  `findhub/bootstrap.py` resolve both by `PROJECT_ROOT`-relative paths. A pipx,
  Homebrew or `.app` install therefore cannot migrate its database or import the
  vendored protocol code. This is why D2 and D3 exist and why they land before any
  feature work.
- `config.py` `database_path = PROJECT_ROOT / "data" / "findplus.sqlite"` puts the
  history inside `site-packages` for installed users, where an upgrade deletes it, and
  prevents the CLI daemon and the desktop app from sharing one file. Hence D1.
- `config.py` has a `pid_file` property that nothing uses; `service.is_running()`
  queries launchctl/systemctl. The Tauri shell needs a real liveness signal, hence D7
  (`daemon.json` + health probe).
- `service.py` writes the Windows Task Scheduler XML to `PROJECT_ROOT / "deploy"`,
  a directory that does not exist. Moves to the state dir (D7).
- `cli.py` `stop` currently calls `service.uninstall()`, which deletes the plist. If
  `stop` merely unloaded the service while the watchdog stayed loaded, the watchdog
  would restart it within five minutes. Hence D8's precise semantics.
- `api.py` (~690 lines), `cli.py` (~670) and `app.js` (966) exceed the 300-line cap.
  Hence D12.

### 12c. mDNS decision (D4)

The app binds `127.0.0.1` only. mDNS advertises a host to *other* machines; an A
record pointing at a loopback address is meaningless off-box and, for the local box,
depends on the resolver accepting a self-published `.local` name that maps to
127.0.0.1, which is not guaranteed on macOS. `zeroconf` is also LGPL-2.1, which is
compatible with GPL-3 but is one more licence to explain. `http://localhost:8647`
needs no explanation. Revisit only if a LAN-bind feature is ever added.

### 12d. Alerts channel decision (D9)

WhatsApp via Twilio or the Meta Cloud API needs business onboarding and credentials
that do not exist in the vault. Shipping untested code for a child-location alert path
contradicts the honesty rule. A generic webhook channel gives ntfy, Discord, Slack,
Home Assistant and any WhatsApp bridge a working path today with zero onboarding.
WhatsApp-native is a v1.1 item and the docs say so.

### 12e. Apple provider decisions (D10, D11)

FindMy.py 0.10.2 bundles `LocalAnisetteProvider` (via the `anisette` package), so the
"point at an Anisette server" instruction in the original brief is outdated: a local
provider is the default, a remote URL is optional. FindMy.py depends on `bleak` (BLE
stack; dbus on Linux) and caps Python at `<3.15`; making it mandatory would bloat
every install and constrain the Python range for Google-only users. It is an optional
extra.

### 12f. Geofence, presence and quorum defaults (D17–D19)

- False EXIT ("left School" while still at school) is the alarming failure, so exits
  need two confirmations and an exit margin; entries need one medium-or-better
  confidence fix. Confidence is `high` when accuracy ≤ radius/2, `medium` when ≤
  radius, otherwise `low` and ignored for state.
- Google returns batches of historical reports out of order; the engine sorts by
  `observed_at` and ignores anything older than the last state change.
- The first confirmed fix for a (place, device) seeds the state silently. Otherwise a
  fresh install would send "ENTER Home" for every tag the moment polling starts.
- Presence needs at least two reporting members to claim `all_together`; one reporting
  member is `partial` with the others named as stale. Zero reporting members is
  `unknown`. Every verdict carries a note sentence that the UI shows verbatim.
- Quorum is computed over non-stale members only; `all` never fires while any member
  is stale.

### 12g. What session 2 did to the working tree

1. `rsync -a --exclude .venv --exclude .pytest_cache --exclude .ruff_cache
   --exclude __pycache__ --exclude data` from `/Users/admin/Developer/bike-tracker/`
   into `/Volumes/UG/Sites/acamarata/findplus/`, preserving `.git`.
2. New venv (`python3.12`), `pip install -e ".[dev]" playwright`; baseline 262 passed.
3. `git mv src/bike_tracker src/findplus`; perl substitutions in 44 files:
   `Bike Tracker`→`Find+`, `BikeTracker`→`FindPlus`, `BIKE_TRACKER`→`FINDPLUS`,
   `bike_tracker`→`findplus`, `bike-tracker`→`findplus`, `bike-history`→`findplus`,
   `8477`→`8647`; `pyproject.toml` name/version/description by hand; `.env.example`
   `DATABASE_PATH` comment neutralised; README heading `# Find+ (findplus)`.
4. Reinstalled editable, re-ran gates: 262 passed, ruff clean, `node --check` clean,
   `findplus --version` → `1.0.0.dev0`.
5. Committed `a6dd275`. Removed an empty stray `docs/` directory. Left
   `PROMPT.md`, `CONTEXT.md`, `PLAN.md` untracked for session 3 to move under
   `.github/docs/` and commit.
6. Did **not** delete `/Users/admin/Developer/bike-tracker` or `~/.bike-tracker`
   (session 3 does, per `PROMPT.md` §1). Did not create any GitHub repo. Did not
   rename the directory.

Test fixtures still use "Bike Tag" as a device name; that is a legitimate device and
stays.

### 12h. Session 3 (2026-09-19, same day): directory renamed, phase tree forged

- The owner authorised the rename: `/Volumes/UG/Sites/acamarata/waypost` → `/Volumes/UG/Sites/acamarata/findplus`;
  the session moved with it; the venv was recreated; 262 passed and ruff clean at the new path.
- The owner added a requirement: a native macOS widget "that works just as good as the Apple Weather one".
  Decision D21 (ADR-P1-03, `specs/widget.md`): Swift WidgetKit extension, sandboxed, reads `GET /api/widget`
  on loopback, no App Groups, embedded into `Find+.app/Contents/PlugIns` after Tauri bundling and re-signed;
  map snapshot opt-in and off by default because `MKMapSnapshotter` sends the coordinate region to Apple.
  Precedent: the cascade project's owner ruling R-16.22 (a thin read-only macOS widget over a daemon API).
- The owner asked for the full PBD/PEWS planning to RTB. Created `.claude/` (PRI, VISION, FEATURES, memory,
  tasks) and `.claude/phases/` (MODE, registry, both status mirrors, routes, INDEX, `current/p1/` with
  phase.yaml, 00-INIT-BRIEF.md, PHASE-PLAN.md, prompt.md, epics-outline.md, decisions.yaml, six Accepted ADRs,
  standing-authorizations.md, EXTERNAL-GATES.md, nine interface specs under `specs/`, the ticket template,
  the E4-T2 exemplar) and `.opencode/phases/sport/` (index, master-inventories, REGISTRY-REUSABLES).
- Restructured the waves so every wave is cross-sprint dependency-free (D23) and moved the structural
  splits to the front (D22): W1 E1 · W2 E2 · W3 E3,E7 · W4 E4,E11 · W5 E5,E8,E12 · W6 E6,E9,E10-S1,E13 ·
  W7 E10-S2,E16 · W8 E14 · W9 E15. Sixteen epics, seventeen sprints, 116 tickets.
- Ticket forging: one conductor T2 (GLM) one-shot per epic from a brief + template + exemplar + outline
  row + PLAN section + the relevant specs; output split into ticket files; linted by a custom exec-lint
  (decision-leak phrases, matrix, checks prefix, length) and by `~/bin/pbd-verify-ready` and
  `~/bin/pbd-verify-dag`. `phase_status` flips to `rtb` only when both gates exit 0.

### 12i. Monorepo layout (owner request, same session)

The owner asked for a minimal root with per-app folders and per-app `.claude` contexts (PAC) under the
acamarata project context, maximal code sharing, fast development and minimal build friction. Done and
committed as `70b220b`: `cli/` (pyproject, src, tests, vendor, migrations), `web/` (dashboard assets), with
`desktop/` to be created by E13/E16; PACs at `cli/.claude`, `web/.claude`, `desktop/.claude`; ADR-P1-07.
The wheel force-includes `../web` at `findplus/web/static` and `api.py::_static_dir()` prefers the packaged
copy, falling back to the repo folder; verified with `python -m build` (assets present in the wheel). The
dashboard stays vanilla JS for 1.0 (APC Policy 2 deviation recorded in the ADR). `mobile/` is not created.
262 tests pass at the new layout (`pythonpath = ["."]` added to `cli/pyproject.toml`; the browser test now
uses `sys.executable`). A wiki skeleton (14 stub pages) and `wiki-sync.yml` were added under `.github/`.

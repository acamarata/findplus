# Find+ (FindPlus) — build-to-completion brief

You are taking over a working, already-renamed application and finishing it as a
public FOSS project. Read this whole file, then `CONTEXT.md` (evidence and history),
then `PLAN.md` (every epic, ticket, file, test and acceptance check). Where they
overlap they agree. This file is the instruction set; do not re-plan what `PLAN.md`
already specifies, and do not undo a decision without reading its reason in
`CONTEXT.md`.

**Owner:** Ali Camarata (github.com/acamarata). Solo maintainer, software/AI engineer.
Do not dumb the implementation down. Do not ask permission for routine engineering
decisions: decide, implement, verify, report. Ask only at the authority boundaries in
§10, and ask them last.

---

## 0. The name (decided by the owner, 2026-09-19)

| Where | Name |
|---|---|
| Display (UI title, menu bar, README heading, dmg window, app bundle) | **Find+** |
| Identifiers where `+` is not allowed (repo, PyPI, Homebrew formula, Python package, CLI, env prefix, state dir, launchd label, bundle id) | **findplus** / **FindPlus** |
| GitHub | `acamarata/findplus` (does not exist yet; it is created at the end, §5d) |
| Python package / CLI | `findplus` |
| Env prefix | `FINDPLUS_*` |
| State dir | `~/.findplus/` |
| Service labels | `com.acamarata.findplus`, `com.acamarata.findplus.watchdog`; systemd `findplus.service`, `findplus-watchdog.{service,timer}`; Task Scheduler `FindPlus`, `FindPlusWatchdog` |
| Session cookie | `findplus_session` |
| Port | **8647**, `http://localhost:8647` |
| macOS app | `Find+.app`, bundle id `com.acamarata.findplus`, dmg file `FindPlus-<version>-<arch>.dmg` (no `+` in file names or URLs) |
| Homebrew | `brew install acamarata/tap/findplus` |

History, so it is not relitigated: the code was born as "bike-tracker". The owner
rejected "Hub+" (ties the name to Google's current branding, which already changed
once) and "FindMyPlus" ("Find My" is Apple's mark). A planning session proposed
"Waypost"; the owner chose **Find+ / FindPlus** because the product now covers both
Google Find Hub and Apple Find My. `findplus` was verified free on PyPI and on
github.com/acamarata on 2026-09-19.

Trademark hygiene that follows from the name: never write "Find My+" or "Find My Plus";
never use Apple's or Google's logos or product icons; refer to the networks
nominatively ("works with Google Find Hub and Apple Find My"). The README carries a
one-line "not affiliated with Apple or Google" notice.

**The rename and the monorepo layout are already done in code.** Layout (ADR-P1-07): `cli/` (package,
tests, vendor, migrations, pyproject), `web/` (dashboard assets), `desktop/` (Tauri + widget, created in
E13/E16), `packaging/`, `.github/`; root files `.gitignore README.md LICENSE CHANGELOG.md install.sh`; each
app folder has a PAC `.claude/CLAUDE.md`. `cli/src/findplus/`, all imports, `cli/pyproject.toml`
(name `findplus`, script `findplus = "findplus.cli:main"`, version `1.0.0.dev0`), env
prefix, state dir, labels, cookie, port, UI title. Commit `a6dd275`. The grep
`grep -rniE "bike[-_ ]tracker|BIKE_TRACKER|BikeTracker|bike-history|8477"` over
`src tests migrations README.md ARCHITECTURE.md cli/pyproject.toml cli/.env.example .gitignore`
returns nothing. 262 tests pass; ruff and `node --check` are clean.

---

## 1. First actions, in order

The directory was named `waypost` during planning. **The owner renames it to
`/Volumes/UG/Sites/acamarata/findplus` before starting your session.** Everything
below assumes that path. Nothing in the code depends on the directory name
(`PROJECT_ROOT` is derived from `__file__`), but the existing `.venv` has absolute
paths baked in and must be recreated.

```bash
cd /Volumes/UG/Sites/acamarata/findplus
git log --oneline | head -3
```
Expect `70b220b refactor: monorepo layout (cli/, web/, desktop/) with a shared dashboard folder` on top of
`a6dd275 chore: rename bike-tracker to findplus` and five older commits.

```bash
launchctl list | grep -iE "bike|findplus"
ls ~/Library/LaunchAgents | grep -iE "bike|findplus"
lsof -iTCP:8647 -sTCP:LISTEN
```
All three must print nothing.

```bash
rm -rf .venv
python3.12 -m venv .venv
./.venv/bin/pip install -e "./cli[dev]" playwright
./.venv/bin/python -m pytest cli/tests/ -q
./.venv/bin/ruff check cli/src cli/tests cli/migrations
./.venv/bin/ruff format --check cli/src cli/tests cli/migrations
node --check web/app.js
```
Expect `262 passed`, ruff clean, node clean. If anything differs, stop and report. Commands run from the
repo root; `pip install -e ./cli` installs the package; the venv stays at the root.

**Then remove the old tree.** The copy was verified green in the new location on
2026-09-19 (262 passed before and after the rename), so the owner's original
instruction to delete the source after verification now applies:

```bash
rm -rf /Users/admin/Developer/bike-tracker
rm -rf ~/.bike-tracker
```
`~/.bike-tracker` holds only `logs/`. There is no history in it (the owner never
completed Google auth). Do **not** write migration code for the old state dir or the
old `data/` database.

Do not create `acamarata/findplus` on GitHub until §5d says so. Do not publish
anything. Do not rename the directory yourself.

Use the fleet dispatch rules from the owner's global instructions: the interactive
session plans, dispatches and reviews; agents execute disjoint scopes; never more than
four local agent processes at once on this 16 GB machine; never two heavy compiles
(`cargo tauri build`, PyInstaller, Playwright installs) at once.

**This build is Phase P1 of the `findplus` project.** No phase state exists yet.
The phase tree already exists at `.claude/phases/current/p1/` (phase.yaml, epics-outline.md, specs/, adrs/,
standing-authorizations.md, EXTERNAL-GATES.md, 116 ticket YAML files): one phase `p1`, sixteen epics `E1`–`E16`,
nine waves, seventeen sprints. `PLAN.md` is the narrative source and the ticket YAML is the contract; do not re-derive either, but do
record any deviation you make as a
ruling in the phase state with its reason.

---

## 2. What already exists — do not rebuild any of this

7,324 lines of Python across 43 files, plus a vanilla-JS dashboard. 262 tests pass.
`ruff check` and `ruff format --check` are clean. Keep them that way.

### The upstream decision (already researched; do not redo)

- **`leonboe1/GoogleFindMyTools`**: GPL-3.0, adopted, vendored at pinned commit
  `d46e9528578015b51d3b84dd91bf8f16e9ab850f` under `cli/vendor/GoogleFindMyTools/`. It
  solves Google's Nova/Spot protocol, FMDN end-to-end encryption, owner-key retrieval
  and the Android auth chain. **Never reimplement that.**
- **`karlmarx/find-hub-tracker`**: rejected (no licence, stdout scraping, drops all but
  the last report of a batch, no deduplication, zero tests). Do not revisit.
- **`malmeloo/FindMy.py`** (MIT, 0.10.2 on PyPI, requires Python `>=3.10,<3.15`,
  depends on `bleak` and `anisette`): the Apple-side dependency. Optional extra, see §4d.

### The one adaptation that matters

Upstream's `get_location_data_for_device()` prints and returns `None`.
`cli/src/findplus/findhub/client.py` calls upstream's own primitives and returns typed
`RawObservation` objects; every report in a batch is retained. No crypto or protocol
code is modified. Two upstream defects are contained there, not inherited. Preserve
both: `exit(1)` on owner-key mismatch is caught as `SystemExit` and re-raised as
`DecryptionError`; the busy-wait on the FCM result is replaced by a `threading.Event`
with `POLL_TIMEOUT_SECONDS`.

### Modules (current, after the rename)

```
cli/src/findplus/
  config.py          Settings (pydantic-settings, env prefix FINDPLUS_); refuses non-loopback binds
  logging_setup.py   structlog + rotating file; redacts tokens/cookies/keys
  geo.py             haversine, movement threshold
  security.py        scrypt PIN hashing, in-memory sessions, brute-force throttle
  appsettings.py     theme / lock / idle prefs in the settings table
  state.py           device tracking selection (is_tracked), key-value settings
  ingest.py          deduplication + persistence
  poller.py          scheduler, per-device sequential polling with 10 s stagger, backoff
  timeline.py        day grouping, gaps, stats, per-device tracks
  exporters.py       CSV / JSON / GPX / KML
  api.py             FastAPI, 24 routes, app-lock middleware        (~690 lines)
  cli.py             16 commands                                     (~670 lines)
  service.py         launchd / systemd / schtasks plans + watchdog
  db/                SQLAlchemy 2.0 models, UtcDateTime, session, Alembic runner
  findhub/           bootstrap (vendor path + secrets redirect), typed client, types
  web/static/        index.html, style.css, app.js (966 lines), vendored Leaflet, icon.svg
cli/migrations/          Alembic env + versions 0001, 0002   (repo root, see §3 D2)
cli/vendor/GoogleFindMyTools/                                 (repo root, see §3 D3)
cli/tests/               17 files, 262 tests (12 Playwright browser tests skip without Chrome)
```

### Invariants — breaking any of these is a regression

1. **Deduplication.** A sighting is `(device_id, observed_at, latitude_e7,
   longitude_e7)` with a DB-level unique constraint. Repeats bump `times_returned`
   and `last_fetched_at` and create no point.
2. **`observed_at` ≠ `fetched_at`.** Timelines use `observed_at`; the UI shows both
   plus the lag.
3. **Coordinates stored as integer 1e-7 degrees.**
4. **All timestamps stored naive-UTC** via a `UtcDateTime` TypeDecorator that raises
   on naive input. Day boundaries are local midnight to next local midnight (23 h /
   25 h on DST days, tested).
5. **Timelines are never merged across devices.**
6. **No interpolation, ever.** A detection gap is drawn as a gap.
7. **Distance is labelled "Approximate distance between observed locations"**
   everywhere, including exports.
8. **Movement filtering annotates, never deletes** (`is_movement` at read time).
9. **Loopback only.** `Settings` raises on any other host unless
   `FINDPLUS_ALLOW_PUBLIC_BIND=1`. No analytics, telemetry or third-party scripts.
   OSM tiles are the one documented external call from the browser; §4b adds
   Telegram / webhook calls **only when the user configures them**.
10. **5-minute poll floor**, overridable only via `ALLOW_FAST_POLLING=true`.
11. **The app lock is enforced server-side** (401 on every data endpoint) and
    `purgeRenderedData()` destroys coordinates already in the DOM.
12. **Never fabricate a location.** A failed poll records status and stores nothing.

### Known-good behaviours worth not regressing

- "No devices tracked" sets `CycleOutcome.config_error` and does not escalate backoff.
- Changing the PIN revokes all sessions then re-issues one to the calling browser.
- The watchdog treats `401` as healthy.
- Sessions are in-memory only, so a restart re-locks.
- Brute-force lockout blocks the correct PIN too.

### Facts discovered during planning that PLAN.md relies on

- `config.py` defines a `pid_file` property (`~/.findplus/findplus.pid`) that **nothing
  writes or reads**. `service.is_running()` asks launchctl/systemctl instead.
- `service.py` writes the Windows task XML to `PROJECT_ROOT / "deploy"`, which does not
  exist and is wrong for an installed package.
- `cli/migrations/` and `vendor/` sit outside `src/`, so the current wheel would ship
  neither (fatal for pipx/Homebrew users).
- `database_path` defaults to `PROJECT_ROOT / "data" / "findplus.sqlite"` (inside
  site-packages once installed).
- `api.py`, `cli.py` and `app.js` exceed the 300-line file cap in the owner's
  engineering standard; every feature below grows them.

---

## 3. Decisions already made (implement these; reasons are in CONTEXT.md §12)

| # | Decision |
|---|---|
| D1 | Default database is `~/.findplus/findplus.sqlite`. `FINDPLUS_DATABASE_PATH` overrides. A dev `.env` may point at `data/`. |
| D2 | Alembic migrations move into the package at `cli/src/findplus/db/migrations/`; `cli/alembic.ini` is deleted; config is built in code. |
| D3 | `cli/vendor/GoogleFindMyTools/` stays untouched at the repo root and is force-included into the wheel at `findplus/_vendor/GoogleFindMyTools/`; bootstrap tries the package path first, then the repo path. |
| D4 | **No mDNS in v1.** The URL is `http://localhost:8647`. `findplus open` and the tray open it. |
| D5 | Migration order: `0003` device provider column, `0004` places, `0005` groups + alerts. |
| D6 | Provider protocol returns `ProviderDevice`, not `FindHubDevice`. |
| D7 | `findplus serve` writes `~/.findplus/daemon.json` (pid, port, version, started_at). "Never two daemons" = health probe + that file + port-bind failure. The Windows task XML goes in the state dir. |
| D8 | `findplus stop` unloads both jobs and leaves the unit files (they return at next login; say so). `findplus uninstall --yes` unloads and deletes both. `findplus restart` kickstarts. |
| D9 | Alert channels: **Telegram** and a generic **webhook** (JSON POST, optional HMAC). WhatsApp-native is deferred to v1.1 and the docs say so. |
| D10 | Apple auth uses FindMy.py's `LocalAnisetteProvider` by default; `FINDPLUS_APPLE_ANISETTE_URL` selects a remote one. |
| D11 | FindMy.py is the optional extra `findplus[apple]`; the provider imports lazily and reports "not installed" cleanly. |
| D12 | `api.py` → `api/` package with routers; `cli.py` → `cli/` package; `app.js` → ES modules. Behaviour-preserving, snapshot-tested, done while adding the new routes. |
| D13 | CI adds a `windows-latest` unit-test job. Windows service management is unit-tested and labelled "community-tested" until someone runs it on real Windows. |
| D14 | The build never blocks on Google sign-in. Everything is verified with fixtures and real protobufs; the owner runs `findplus auth` at handoff. |
| D15 | `findplus start` state machine: not authenticated → print the two commands, exit 0; authenticated but nothing tracked → refresh devices, open dashboard on `#devices`, exit 0; otherwise install/bootstrap the service and open the dashboard. |
| D16 | The MCP server is a thin client of the running daemon's HTTP API, so the app lock applies to it automatically. |
| D17 | Geofence defaults: `enter_confirmations=1`, `exit_confirmations=2`, exit margin `max(accuracy, 50 m)`, fixes with accuracy worse than the radius are indeterminate and never change state, the first confirmed fix seeds state without an event. |
| D18 | Presence: `stale_after_minutes=90`, `cluster_radius_meters=150`, verdict `all_together` needs at least two reporting members; a single reporting member is `partial` and names who is stale. |
| D19 | Group alert quorum `any|majority|all|<int>` over **non-stale** members, window 30 min, one group event per (group, place, type, window). |
| D20 | Version: `1.0.0.dev0` now; `v1.0.0` is the first public release, owner-approved. |
| D21 | macOS widget: WidgetKit extension in Swift under `desktop/widget`, sandboxed, reads `GET /api/widget` on loopback, no App Groups, embedded into `Find+.app/Contents/PlugIns` after bundling and re-signed; map snapshot opt-in, default off. |
| D22 | Structural splits of `api.py`, `cli.py`, `app.js`, `service.py` happen first (E1), before any feature. |
| D23 | Waves are cross-sprint dependency-free: W1 E1 · W2 E2 · W3 E3,E7 · W4 E4,E11 · W5 E5,E8,E12 · W6 E6,E9,E10-S1,E13 · W7 E10-S2,E16 · W8 E14 · W9 E15. |

---

## 4. Features to build (full ticket detail in PLAN.md)

### 4a. Places and geofences

Named circular zones (Home, School, Grandma's, Store). Migration `0004`: `places`,
`place_events` (with `confidence`, `distance_meters`, `accuracy_meters`,
`observation_id`, `notified_at`), `place_states` (per place × device: state, streak,
`since_observed_at`). Evaluate in `ingest.py` immediately after a **new** observation
is inserted; duplicates never reach it. Hysteresis per D17, tested with a jitter
fixture (40 alternating fixes around the radius produce exactly one ENTER and no
EXIT). Observations are processed in `observed_at` order; backfilled older reports
never move state. UI: circles on the map, add/edit/delete dialog with click-to-place.
CLI: `findplus places list|add|edit|remove|events`.

### 4b. Alerts

Settings → Alerts. Rules: place × (group or device) × ENTER/EXIT × channel × cooldown.
**Telegram:** bot token + chat id, with `findplus alerts telegram-setup` that validates
the token with `getMe`, then polls `getUpdates`, tells the user to message the bot and
captures the chat id automatically. Handle `409 Conflict` (a webhook already exists on
that bot) by explaining it; never call `deleteWebhook` on the user's bot. **Webhook:**
JSON POST with optional HMAC signature. Tokens live in `~/.findplus/alerts.json`
(0600), never in the DB, git or logs (`_SENSITIVE_KEYS` extended). Cooldown per (rule,
place, subject) and de-dup per event id; a 200-event flapping fixture must produce one
message. Every message carries observed time, reported time and the lag.
`findplus alerts test` sends one message.

### 4c. Device groups and presence logic

Migration `0005`: `groups` (quorum, cluster radius, stale threshold), `device_group`,
`group_place_events`. `GroupPresence` per D18: each member is `present_at_place`,
`moving`, `stale` or `unknown`; verdict `all_together`, `partial` (names diverged and
stale members) or `unknown`; a mandatory `note` sentence the UI shows verbatim.
**Stale is never "at home" and never "left behind".** Group alerts per D19. UI: group
selector beside the device filter; per-member coloured tracks (never merged); presence
panel with the note. CLI: `findplus groups list|add|remove|members|presence|events`.

### 4d. Multi-provider architecture

`findplus/providers/` with `LocationProvider` protocol (`name`, `display_name`,
`is_available()`, `is_authenticated()`, `authenticate()`, `describe_auth()`,
`list_devices() -> list[ProviderDevice]`, `locate() -> list[RawObservation]`), a
registry with an entry-point group `findplus.providers`, and migration `0003` adding
`devices.provider`. The Google client moves to `providers/google_findhub/` unchanged.
The Apple provider (`providers/apple_findmy/`) uses FindMy.py per D10/D11:
`findplus auth --provider apple-find-my`, accessories registered from a pairing
`.plist` or an OpenHaystack private key, `device_id = "apple:" + sha256(raw private-key bytes).hexdigest()[:24]` (the private key is what both the .plist and the OpenHaystack export carry; hashing its raw bytes is stable across encodings).
State the limits everywhere: keys you hold; DIY tags work well; real AirTags require
extracting pairing keys, which most users cannot do; Apple may act against accounts
used this way. Ship Google-only if Apple overruns its two-day budget, and say so.

### 4e. MCP server

`findplus mcp [--allow-writes]` over stdio using the `mcp` SDK (2.x), implemented as
an HTTP client of the daemon (D16). Read tools: `list_devices`, `list_groups`,
`list_places`, `get_latest`, `get_timeline`, `get_place_events`,
`get_group_presence`, `get_status`, `export`. Write tools only with the flag:
`poll_now`, `add_place`, `remove_place`, `add_group`, `set_group_members`, `lock`.
`unlock(pin)` holds a session cookie inside the MCP process; while locked every other
tool returns `{"locked": true}`. Never expose PIN changes, history deletion or alert
credentials.

---

## 5. Distribution

Two audiences, one codebase: CLI/daemon for terminal users, a double-clickable macOS
app for everyone else. Same SQLite database, same daemon, same local API. Port 8647.

### 5a. CLI install paths (build all three)

1. **Homebrew:** `brew install acamarata/tap/findplus` (create `acamarata/homebrew-tap`
   at the end, with the repo).
2. **curl | bash:** `curl -fsSL https://raw.githubusercontent.com/acamarata/findplus/main/install.sh | bash`.
   Short, readable, pinned, idempotent, prints its plan and asks unless `--yes` or
   `FINDPLUS_YES=1`; venv under `~/.local/share/findplus`, symlink in `~/.local/bin`.
3. **PyPI:** `pipx install findplus`.

First run on a bare machine, exactly two commands, **no inline comments** (the owner's
first attempt failed because a pasted `#` comment became a CLI argument):

```bash
findplus auth
findplus start
```

### 5b. Background service

`findplus start|stop|restart|status|uninstall` per D8/D15, plus `findplus doctor
[--repair]`. Always print the exact unit file and load command before writing; require
confirmation unless `--yes`. User-level only; never `/Library`, `/etc` or sudo (tested
by asserting every path starts with `$HOME`). Three layers: `RunAtLoad` + `KeepAlive`
+ a separate watchdog job every 5 minutes that treats `401` as healthy. Windows gets a
`FindPlusWatchdog` scheduled task.

### 5c. macOS desktop app (Tauri)

`Find+.app` in a dmg on GitHub Releases. Tauri 2 shell, no JavaScript build: a static
splash page, then a window at `http://127.0.0.1:8647/` once the daemon answers. The
daemon is a **PyInstaller onedir** sidecar `findplus-daemon`. Supervision: probe
`/api/health`; if a LaunchAgent exists, kickstart it; else spawn the sidecar as a
child; never two daemons.

**Widget (D21, `specs/widget.md`):** a WidgetKit extension (small/medium/large) as polished as Apple's Weather widget: status dot, tracked count, latest positions with honest ages, group verdicts, "Poll now" and "Open Find+" intents, lock-aware, optional map snapshot (off by default). Built with xcodebuild, embedded into the app bundle, re-signed.

Menu-bar dropdown, in this order: `[coloured dot] status line` (green polling
normally, amber stale or daemon not answering, red auth/decrypt failure or repeated
errors, grey locked) · latest location summary (hidden when locked) · tracked-device
count · **Poll Now** · **Lock** · **Open Dashboard** · **Settings** · separator ·
**Open App** · **Quit**. The tray polls the local `/api/status` every 45 s and never
triggers a Google query. "Start at login" is an opt-in toggle that installs the same
LaunchAgent pointing at the bundled sidecar.

Signing: Developer ID identity `Aric Camarata (5398R82926)` is in the keychain; the
vault holds the notarisation API key. Sign every Mach-O inside the PyInstaller bundle
with hardened runtime and the entitlements PyInstaller needs, then let Tauri sign and
notarise the outer bundle; verify with `spctl -a -vv`. CI signing needs a `.p12`
export that does not exist yet (§10). **Never present an unsigned build as a clean
install**; if signing is unavailable, document right-click → Open prominently.

### 5d. Repo setup on github.com/acamarata/findplus (end of build)

Public, **GPL-3.0-or-later** (required by the vendored GPL-3.0 code; FindMy.py is
MIT). Description, topics, README with **real screenshots** produced by a script,
wiki in `.github/wiki/` (Home, Install, First run, Devices & groups, Places & alerts,
App lock, Privacy & threat model, macOS app, CLI reference, API reference, MCP,
Providers, Troubleshooting, FAQ, Contributing), `ci.yml` (ruff + pytest on macOS,
Linux, Windows; Python 3.12/3.13, 3.14 experimental; browser tests on macOS),
`release.yml` (tag → wheel/sdist → PyPI via trusted publishing behind an approval
environment → dmg build/sign/notarise → GitHub Release → tap PR),
`CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue/PR templates,
Dependabot. No AI attribution anywhere (a global pre-commit hook enforces it). Clean
root: `.gitignore`, `README.md`, `LICENSE`, `CHANGELOG.md`, `cli/pyproject.toml`,
`install.sh` plus directories; `PROMPT.md`, `CONTEXT.md`, `PLAN.md` and
`ARCHITECTURE.md` move to `.github/docs/` before the first push. Every deploy step
must also be runnable locally (`packaging/scripts/release-local.sh`); a release must
never depend on GitHub Actions being able to run.

---

## 6. Honesty requirements (non-negotiable)

This app touches a child's location history. Every surface must state, and must not
overstate:

- The Find Hub network notice stays verbatim: locations are reported by nearby
  participating Android devices, can be delayed, sparse or unavailable, and **this is
  not real-time emergency or child-safety GPS tracking**. Apple's network has the same
  properties; say so on Apple surfaces.
- The app lock is deterrence, not encryption at rest. Say FileVault.
- Geofence alerts inherit the network latency. "Arrived at School" may be 40 minutes
  late. The docs and every alert message say so.
- Group presence with stale members is `unknown` or `partial`, never a confident
  answer. Stale is not "at home".
- "Not affiliated with Apple or Google."

---

## 7. Quality gates — every one must pass before you call anything done

```bash
./.venv/bin/python -m pytest cli/tests/ -q
./.venv/bin/ruff check cli/src cli/tests
./.venv/bin/ruff format --check cli/src cli/tests
node --check web/app/*.js
shellcheck install.sh
bash packaging/scripts/stage-sidecar-stub.sh
cargo clippy --manifest-path desktop/src-tauri/Cargo.toml -- -D warnings
cargo test --manifest-path desktop/src-tauri/Cargo.toml
```

- `stage-sidecar-stub.sh` must run before the two `cargo` commands on a clean
  checkout: `desktop/src-tauri/resources/findplus-daemon/` is gitignored (a
  real PyInstaller build populates it), but `tauri_build::build()` validates
  `tauri.conf.json`'s `bundle.resources` glob on every `cargo build`/`clippy`/
  `test`, so a fresh clone or worktree fails with "glob pattern
  resources/findplus-daemon/\*\*/\* path not found" before clippy even runs.
  The script is idempotent and never overwrites a real sidecar build
  (`.github/workflows/ci.yml`'s `desktop` and `notify-rust-tests` jobs already
  run it first).

- Every new feature gets tests. Tests never touch the real Google or Apple account,
  the real state dir or the network (an autouse fixture blocks non-loopback sockets).
- The pure engines (`geofence.py`, `presence.py`, `quorum.py`, `dispatch.py`) carry a
  95 % line-coverage floor.
- Run the app and **screenshot it** for every UI change. Two real bugs were found only
  that way (a modal open on load; coordinates left in the DOM after locking).
- `findplus doctor` must stay accurate.
- Acceptance checklist: `PLAN.md` §6.

---

## 8. Then, and only then

Report completion to the owner with a step-by-step for:
1. `findplus auth` (warn: the upstream Chrome driver runs `pkill -f chrome` and closes
   open Chrome windows),
2. selecting devices (expect phones in the Find Hub list, not just tags; tracking all
   inflates the request rate and stores phone history),
3. creating groups and places, wiring Telegram alerts,
4. start/stop/uninstall and the three-layer redundancy story,
5. installing the dmg and what the tray shows.

State plainly what is proven (fixtures, real protobufs, packaging, signing) and what is
not (live Google decryption, live Apple reports, Windows on real Windows). The owner
has not completed Google auth; the live path has never run against a real device.

---

## 9. Working style

Build the FOSS product first, then the owner uses it. Nothing hard-coded to his
machine, account, devices or paths. Work autonomously and fast. Parallelise where
scopes are disjoint (`PLAN.md` §3 gives the lanes) but keep one owner for the core so
the architecture stays coherent. Report faithfully; if something is incomplete, say
which part and why. Human tone in every doc: no em-dash connectors, no "seamlessly",
"robust", "leverage", "dive into"; short sentences, active verbs.

---

## 10. Owner boundaries (ask these last, numbered, each with its default)

1. First public push of `acamarata/findplus` and creation of `acamarata/homebrew-tap`
   (public identity). Default: when `PLAN.md` E14-T10 passes.
2. Publish `v1.0.0` to PyPI and GitHub Releases (external outbound). Default: TestPyPI
   rehearsal only; real publish on an explicit "publish".
3. Export the Developer ID certificate as a `.p12` into a repo secret for CI signing
   (credential). Default: local signed builds only until provided.
4. Register the PyPI pending publisher for `acamarata/findplus` (credential). Default:
   the release job stays blocked at its approval environment.
5. Google sign-in on the owner's machine (credential; closes Chrome). Default: last
   step of the handoff, owner-run.

# Find+ (FindPlus) — Phase P1 implementation plan

Date: 2026-09-19. Project `findplus`, phase **P1: "Find+ 1.0"**, repo-to-be
`acamarata/findplus`. Companion documents: `PROMPT.md` (instructions and decisions
D1–D23), `CONTEXT.md` (evidence). This file is the narrative ticket source: sixteen epics
in nine waves. The forged phase tree (`.claude/phases/current/p1/`, ticket YAML, pinned
interface specs) was created from it on 2026-09-19 and is the build contract; where the
two differ, the ticket YAML and `specs/` win.

Read order for any builder: `PROMPT.md` §2 invariants and §3 decisions →
`CONTEXT.md` §12 → the ticket.

Naming used throughout: display **Find+**, identifiers `findplus` / `FindPlus`,
env `FINDPLUS_*`, state dir `~/.findplus/`, port 8647, labels
`com.acamarata.findplus{,.watchdog}`, cookie `findplus_session`, bundle id
`com.acamarata.findplus`, app `Find+.app`, dmg `FindPlus-<ver>-<arch>.dmg`.

---

## 0. Verified starting state (2026-09-19, after session 2)

| Item | State |
|---|---|
| Source | `/Volumes/UG/Sites/acamarata/findplus` (owner renames to `findplus`), 6 commits, clean tree, `PROMPT.md`/`CONTEXT.md`/`PLAN.md` untracked |
| Suite | **262 passed** after the rename; ruff check + format clean; `node --check` clean |
| Old install | no launchd jobs, no plists, `~/.bike-tracker/` has only `logs/`; the old source tree still exists and is deleted in E1-T1 |
| Ports | 8477 and 8647 free |
| Toolchain | python3.12 (venv), tauri-cli 2.11.4, cargo 1.98.0, node 24 / pnpm (unused), Xcode, valid Developer ID Application identity |
| Vault | Apple notarisation API key + signing identity name present; **no** `.p12`, **no** PyPI token, **no** Twilio/Meta |
| Names | `findplus` free on PyPI and github.com/acamarata; `acamarata/homebrew-tap` does not exist |
| Libraries | findmy 0.10.2 (`>=3.10,<3.15`, bleak + anisette), mcp 2.2.0, pyinstaller 6.22.3, tauri 2.11.5, tauri-plugin-positioner 2.3.4, tauri-plugin-shell 2.3.6, tauri-plugin-single-instance 2.4.4 |

---

## 1. Decisions this plan implements (summary; full text in PROMPT.md §3)

D1 state-dir DB · D2 migrations in package · D3 vendor force-included · D4 no mDNS ·
D5 migration order 0003 provider / 0004 places / 0005 groups+alerts · D6
`ProviderDevice` · D7 `daemon.json` + health probe, task XML in state dir · D8
stop/uninstall/restart semantics · D9 Telegram + webhook, WhatsApp deferred · D10
local Anisette · D11 `findplus[apple]` extra · D12 split api/cli/app.js · D13 Windows
CI job · D14 no gate on Google auth · D15 `start` state machine · D16 MCP over HTTP ·
D17 geofence defaults · D18 presence defaults · D19 quorum · D20 version `1.0.0.dev0`
→ `v1.0.0`.

Not changed from the original brief: every invariant, GPL-3.0-or-later, port 8647,
tray menu order, no interpolation, no telemetry, honesty text.

---

## 2. Target repository layout (ADR-P1-07, committed 70b220b)

```
findplus/
  .gitignore  README.md  LICENSE  CHANGELOG.md  install.sh          # minimal root
  cli/                                   # the core: daemon, CLI, REST API, MCP (PAC: cli/.claude/CLAUDE.md)
    pyproject.toml  README.md  alembic.ini (deleted in E2-T2)  .env.example
    src/findplus/
      __init__.py  __main__.py  config.py  logging_setup.py  geo.py  security.py
      appsettings.py  state.py  ingest.py  poller.py  timeline.py  exporters.py
      service/   plan.py  launchd.py  systemd.py  schtasks.py  watchdog.py  runtime.py
      api/       __init__.py (create_app, lock middleware, _PUBLIC)  deps.py  routes_core.py  routes_devices.py
                 routes_history.py  routes_lock.py  routes_settings.py  routes_places.py  routes_groups.py
                 routes_alerts.py  routes_providers.py
      cli/       __init__.py  main.py  cmd_service.py  cmd_devices.py  cmd_history.py  cmd_places.py  cmd_groups.py
                 cmd_alerts.py  cmd_providers.py  cmd_mcp.py  cmd_config.py  cmd_db.py  cmd_apple.py  cmd_widget.py  _fmt.py
      db/        models.py  types.py  session.py  migrate.py  migrations/ (env.py, versions/0001..0005)
      providers/ __init__.py  base.py  google_findhub/  apple_findmy/
      findhub/   deprecation shim (removed before v1.0)
      places/    __init__.py  geofence.py  events.py
      groups/    __init__.py  presence.py  quorum.py
      alerts/    __init__.py  store.py  rules.py  dispatch.py  channels/{base,telegram,webhook}.py
      mcp/       __init__.py  server.py  tools_read.py  tools_write.py  client.py
      web/static/                        # NOT in git: the wheel force-includes ../web here at build time
    tests/       (mirrors src; ui/ for Playwright; INVARIANTS.md)
    vendor/GoogleFindMyTools/            # untouched, GPL-3.0, LICENSE kept; force-included at findplus/_vendor/
  web/                                   # dashboard assets (PAC: web/.claude/CLAUDE.md); served at /static and /
    index.html  style.css  icon.svg  app.js (→ app/*.js in E1-T6)  vendor/leaflet/
  desktop/                               # macOS app (PAC: desktop/.claude/CLAUDE.md)
    README.md  ui/ (static splash)  src-tauri/ (Cargo.toml, tauri.conf.json, entitlements.plist, src/*.rs, icons/, binaries/)
    widget/ (FindPlusWidget.xcodeproj, Sources/, Tests/, reload-widgets.swift)
  packaging/   pyinstaller/findplus-daemon.spec  entitlements.plist  homebrew/findplus.rb.tmpl
               scripts/ sign-sidecar.sh  embed-widget.sh  sidecar-smoke.sh  screenshots.py  gen-cli-docs.py
                        gen-api-docs.py  lint-prose.sh  release-local.sh  bump-version.sh  third-party-licenses.py
                        create-repos.sh  gen-formula.sh  sync-web.sh
  .github/     workflows/ ci.yml  release.yml  screenshots.yml  wiki-sync.yml
               ISSUE_TEMPLATE/  PULL_REQUEST_TEMPLATE.md  wiki/ (14 pages)  docs/ (PROMPT, CONTEXT, PLAN, ARCHITECTURE,
               THIRD-PARTY, screenshots/)  CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md  dependabot.yml
  .claude/     PRC + phase state (gitignored)   .opencode/phases/sport/ (gitignored)
```

`mobile/` is deliberately absent (ADR-P1-07): the daemon runs on a computer and binds loopback only; a phone
shell needs a LAN/remote product decision first.

---

## 3. Epics, waves, dependencies and dispatch lanes

Canonical ids, sprints and dependency edges: `.claude/phases/current/p1/epics-outline.md`. Waves are
cross-sprint dependency-free (D23); tickets inside a sprint run in id order.

| Wave | Epic | Name | Depends on | Lane | Tickets |
|---|---|---|---|---|---|
| W1 | E1 | Baseline, hygiene, structural splits (api/cli/app.js/service) | — | core owner, serial | 8 |
| W2 | E2 | Packaging foundations | E1 | core owner, serial | 7 |
| W3 | E3 | Provider abstraction | E2 | core owner | 6 |
| W3 | E7 | Service management | E2 | agent D (disjoint files) | 7 |
| W4 | E4 | Places and geofences | E3 | engine agent A | 7 |
| W4 | E11 | Apple provider | E3 | agent G | 6 |
| W5 | E5 | Groups and presence | E4 | engine agent B | 6 |
| W5 | E8 | API + CLI completion (version, widget endpoint, status fields, lock sweep, drift scripts) | E4, E7 | core owner | 5 |
| W5 | E12 | CLI distribution | E4 | agent H | 7 |
| W6 | E6 | Alerts | E5 | engine agent C | 8 |
| W6 | E9 | MCP server | E5 | agent E | 5 |
| W6 | E10-S1 | Web UI: places, groups, providers | E5 | agent F | 5 |
| W6 | E13 | macOS app (Tauri + sidecar) | E5, E7, E12 | agent I (sole heavy-compile lane) | 11 |
| W7 | E10-S2 | Web UI: alerts tab, browser tests, screenshots | E6, E13 | agent F | 4 |
| W7 | E16 | macOS widget (WidgetKit) | E13, E6 | agent I | 8 |
| W8 | E14 | Repo, docs, CI, release | E16, E10-S2 | agent J | 10 |
| W9 | E15 | QA & Done, handoff | E14 | core owner | 6 |

Totals: 16 epics · 9 waves · 17 sprints · 116 tickets.

Dispatch: one-shot text (docs, wiki, reviews) → conductor T3/T2; agentic code → fleet accounts in the
owner's quota order; the interactive session orchestrates and reviews. Local ceiling: ≤ 4 agent
processes, one heavy compile at a time.

Ticket IDs: `P1-E<e>-W<w>-S<s>-T<n>` (files `T-P1-E<e>-W<w>-S<s>-T<n>-<slug>.yaml`). Weight S (< 1 h),
M (1–3 h), L (3–8 h). Every ticket ends with the gates in `PROMPT.md` §7 (the subset that applies).

## 4. Tickets

### E1 — Baseline, hygiene and structural splits (W1, D22)

**E1-T1 (S) Confirm, re-create the venv, prove green, delete the old tree.** Checks and commands exactly as
`PROMPT.md` §1; record the pytest count; then `rm -rf /Users/admin/Developer/bike-tracker` and
`rm -rf ~/.bike-tracker` (standing authorization). Accept: 262 passed; only the planning docs untracked.

**E1-T2 (S) Root hygiene.** Move `ARCHITECTURE.md`, `PROMPT.md`, `CONTEXT.md`, `PLAN.md` → `.github/docs/`.
Add `CHANGELOG.md` (`[Unreleased]`). `.gitignore` additions: `desktop/src-tauri/target/`, `desktop/src-tauri/gen/`,
`desktop/src-tauri/binaries/`, `desktop/widget/build/`, `packaging/build/`, `*.dmg`, `.claude/`, `.opencode/`.
Accept: root = `.gitignore README.md LICENSE CHANGELOG.md cli/pyproject.toml` + dirs.

**E1-T3 (S) Metadata.** `cli/pyproject.toml` per `specs/packaging-and-release.md` (keywords, classifiers, urls,
dev/bundle extras, markers); `findplus/__init__.py` reads the version via `importlib.metadata`.
Accept: `python -m build --outdir dist cli` + `twine check dist/*` pass.

**E1-T4 (L) Split `api.py` into `api/`.** `create_app()` in `api/__init__.py` with the lock middleware and
`_PUBLIC`; routers `routes_core/lock/settings/devices/history.py` via `APIRouter`. Snapshot test: the
`(method, path)` table before/after is identical for the 24 routes. Existing tests unchanged.

**E1-T5 (M) Split `cli.py` into `cli/`.** `cli/main.py` group; `cmd_service/devices/history/_fmt.py`.
`findplus --help` snapshot; every command and option preserved.

**E1-T6 (M) Split `app.js` into ES modules** under `web/static/app/` (`main, api, state, map, timeline,
devices, settings, lock`). `<script type="module">`. Test: every script/link is same-origin and exists.

**E1-T7 (M) Split `service.py` into `service/`** (`plan, launchd, systemd, schtasks, watchdog, runtime`).
Behaviour-preserving; tests updated for import paths only.

**E1-T8 (S) `cli/tests/INVARIANTS.md` + commit** `refactor: package layout for api, cli, service and app.js`.

### E2 — Packaging foundations

**E2-T1 (M) State dir owns everything (D1).**
- `config.py`: `database_path` default `state_dir / "findplus.sqlite"`; `log_dir =
  state_dir / "logs"`; `alerts_file`, `daemon_file`, `apple_dir`, `task_xml_path`
  properties; `ensure_state_dir()` creates it 0700. Remove the unused `pid_file`
  property (replaced by `daemon_file`).
- pydantic-settings `env_file = [state_dir / "config.env", ".env"]`, later wins.
- Tests `cli/tests/test_config_and_logging.py`: default DB under a monkeypatched `HOME`;
  cwd `.env` overrides; `FINDPLUS_DATABASE_PATH` overrides both; state dir mode.
- Accept: fresh `HOME` → `findplus doctor` prints paths under `~/.findplus`.

**E2-T2 (M) Migrations inside the package (D2).**
- `git mv migrations cli/src/findplus/db/migrations`; `db/migrate.py` builds
  `alembic.config.Config()` in code (`script_location` from
  `importlib.resources.files("findplus.db") / "migrations"`); delete `cli/alembic.ini`;
  ruff `extend-exclude` → `cli/src/findplus/db/migrations/versions`.
- Tests `cli/tests/test_migrations.py`: empty → head; head → base; exactly one head.
  `cli/tests/test_wheel_install.py` (`@pytest.mark.slow`): build wheel, install into a
  throwaway venv, run `findplus db upgrade` from `/tmp`.
- Accept: `unzip -l dist/*.whl | grep migrations/versions/0001` present.

**E2-T3 (M) Vendor tree inside the wheel (D3).**
- `pyproject`: `[tool.hatch.build.targets.wheel.force-include]
  "cli/vendor/GoogleFindMyTools" = "findplus/_vendor/GoogleFindMyTools"`; sdist includes
  `vendor/`. `findhub/bootstrap.py::ensure_gfmt_importable()` tries
  `[package/_vendor/GoogleFindMyTools, repo/vendor/GoogleFindMyTools]`.
- Tests: editable mode resolves the repo path; the wheel test imports
  `findplus.providers.google_findhub` from `/tmp` (after E3, update then).
- Accept: `unzip -l dist/*.whl | grep _vendor/GoogleFindMyTools/LICENSE` present.

**E2-T4 (S) Daemon runtime file (D7).** `service/runtime.py`: `write_daemon_file()`
on `serve` start (pid, port, version, started_at, argv), removed on clean exit;
`read_daemon_file()`; `daemon_alive()` = pid alive **and** `/api/health` on that port
answers with `app == "findplus"`. `/api/health` gains `app`, `version`, `pid`. Tests:
stale file with dead pid → not alive; live stub server → alive.

**E2-T5 (S) `findplus config get|set|list|path`.** Writes `~/.findplus/config.env`
(0600) after validating through `Settings` (rejects non-loopback host without the
allow flag; rejects `poll_interval_minutes < 5` without `ALLOW_FAST_POLLING`). Tests
`cli/tests/test_cli_config.py`.

**E2-T6 (S) `findplus db upgrade|current`** (explicit; startup still auto-upgrades).
Tests.

**E2-T7 (S) Commit** `feat: package-safe paths and state dir`; wheel test green.

### E3 — Provider abstraction

**E3-T1 (M) `providers/base.py`.**
```python
@dataclass(frozen=True)
class ProviderDevice: provider: str; device_id: str; name: str; kind: str | None; raw: dict
class LocationProvider(Protocol):
    name: str; display_name: str
    def is_available(self) -> tuple[bool, str]: ...
    def is_authenticated(self) -> bool: ...
    def authenticate(self, interactive: bool = True) -> str: ...
    def describe_auth(self) -> dict: ...
    def list_devices(self) -> list[ProviderDevice]: ...
    def locate(self, device_id: str, name: str) -> list[RawObservation]: ...
```
`RawObservation` moves here (re-exported from the old location) and gains
`provider: str`. Registry `get_provider(name)`, `available_providers()`, entry-point
group `findplus.providers`. Tests `cli/tests/providers/test_registry.py`.

**E3-T2 (M) Google provider = existing client, moved.** `git mv cli/src/findplus/findhub
cli/src/findplus/providers/google_findhub`; `provider.py` wraps `FindHubClient`;
`findplus/findhub/__init__.py` becomes a shim with a `DeprecationWarning`. No crypto or
protocol change. Tests: `cli/tests/test_findhub_client.py` →
`cli/tests/providers/test_google_findhub.py`, assertions unchanged; a test imports every
vendored `_pb2` module.

**E3-T3 (S) Migration `0003_device_provider`.** `devices.provider VARCHAR(32) NOT
NULL DEFAULT 'google-find-hub'`, index `ix_devices_provider`. Tests: existing rows get
the default; downgrade drops it.

**E3-T4 (M) Poller and ingest are provider-aware.** `poll_device` resolves the
provider from `device.provider`; an unavailable or unauthenticated provider records
`PollOutcome(status="provider_unavailable")` without escalating backoff. `upsert_device`
takes `provider`. Tests `cli/tests/test_poller.py`: two fake providers polled with the
stagger; unavailable provider → status recorded, other device still polled, backoff
untouched.

**E3-T5 (S) API/CLI surface.** `GET /api/providers`; `/api/devices` rows include
`provider`; `findplus providers`; `findplus auth [--provider NAME]` (default
`google-find-hub`; bare `findplus auth` unchanged). Tests.

**E3-T6 (S) Commit** `feat: provider abstraction`; ARCHITECTURE § Providers.

### E4 — Places and geofences

**E4-T1 (M) Migration `0004_places`.**
- `places(id PK, name UNIQUE, latitude_e7, longitude_e7, radius_meters INT CHECK >= 20,
  color VARCHAR(16), enter_confirmations INT DEFAULT 1, exit_confirmations INT DEFAULT 2,
  created_at, updated_at)`
- `place_events(id PK, place_id FK, device_id FK, group_id NULL, event_type CHECK IN
  ('ENTER','EXIT'), observed_at, fetched_at, observation_id FK, confidence CHECK IN
  ('high','medium','low'), distance_meters FLOAT, accuracy_meters FLOAT NULL,
  notified_at NULL)`, index `(place_id, device_id, observed_at)`
- `place_states(place_id, device_id, state CHECK IN ('inside','outside','unknown'),
  since_observed_at, streak INT, streak_side, last_observation_id, updated_at,
  PK(place_id, device_id))`
- Tests: up/down; CHECK constraints reject bad rows.

**E4-T2 (L) Geofence engine `places/geofence.py`** (pure, D17):
- `classify(place, obs) -> Classification(side, confidence, distance)`: `d =
  haversine`; `acc = obs.accuracy_meters or 100`; confidence `high` if `acc <=
  radius/2`, `medium` if `acc <= radius`, else `low` → `indeterminate`, never changes
  state. `inside` if `d <= radius`; `outside` if `d > radius + max(acc, 50)`; between
  the rings → `indeterminate`.
- `advance(state, classification, place) -> (new_state, event | None)`: consecutive
  same-side classifications increment `streak`; ENTER when `streak >=
  enter_confirmations` from `outside|unknown`; EXIT when `streak >=
  exit_confirmations` from `inside`; from `unknown` the first confirmed side seeds
  state with no event; observations older than `since_observed_at` are backfill and
  ignored (`geofence_backfill_ignored` log).
- Tests `cli/tests/places/test_geofence.py` (≥ 25): jitter fixture (40 fixes alternating
  80 m / 120 m around a 100 m radius, 30 m accuracy) → exactly one ENTER, zero EXIT;
  EXIT only after two fixes beyond `radius + margin`; ±500 m fix on a 100 m fence →
  indeterminate; backfill ignored; first fix seeds silently; naive datetime raises.

**E4-T3 (M) Wiring in `ingest.py`.** After a **new** row is inserted, in the same
session before commit, `places.events.evaluate(session, observation)` loads states for
all places, runs `advance`, persists `place_states` and `place_events`, returns the
events. Duplicates never reach it. Tests `cli/tests/places/test_ingest_hook.py`: repeat
fix → no event; out-of-order two-report batch handled in observed order; event carries
`observation_id` and `confidence`.

**E4-T4 (M) Repository `places/__init__.py`:** `list_places`, `create_place`
(unique name, radius ≥ 20, lat/lon range), `update_place`, `delete_place` (cascade),
`list_place_events(...)`, `current_presence(device_id)`. Tests `cli/tests/places/test_repo.py`.

**E4-T5 (M) API `api/routes_places.py`:** `GET/POST /api/places`, `PUT/DELETE
/api/places/{id}`, `GET /api/places/events`, `GET /api/places/presence`. 422 with
field names on validation errors; 401 when locked. Tests `cli/tests/test_api_places.py`.

**E4-T6 (S) CLI `findplus places list|add|edit|remove|events`** (`remove --yes`;
`events --format table|csv|json`). Tests `cli/tests/test_cli_places.py`.

**E4-T7 (S) Commit** `feat: places and geofences with hysteresis`. Exports stay
observation-only.

### E5 — Groups and presence

**E5-T1 (M) Migration `0005_groups_alerts`.** `groups(id, name UNIQUE, color, quorum
VARCHAR(16) DEFAULT 'majority', cluster_radius_meters INT DEFAULT 150,
stale_after_minutes INT DEFAULT 90, created_at)`; `device_group(device_id FK, group_id
FK, PK both)`; `group_place_events(id, group_id, place_id, event_type, observed_at,
member_event_ids JSON, members_crossed INT, members_considered INT, members_stale INT,
confidence, notified_at)`; plus `alert_rules` and `alert_deliveries` from E6-T4 (one
migration). Tests as E4-T1.

**E5-T2 (L) Presence engine `groups/presence.py`** (pure, D18):
```python
MemberStatus(device_id, name, status: present_at_place|moving|stale|unknown, place,
             last_observed_at, age_minutes, accuracy_meters, lat, lon)
GroupPresence(group_id, verdict: all_together|partial|unknown, together, diverged,
              stale, reporting_count, considered_count, cluster_radius, window, note)
```
- `stale` if `now - last_observed_at > stale_after`; `present_at_place` from
  `place_states`; `moving` if the last two fixes in the window are farther apart than
  the movement threshold; else `unknown` ("seen recently, not at a named place").
- `all_together` iff `reporting_count >= 2` and every pairwise distance between
  reporting members' latest fixes ≤ `cluster_radius + max(acc_i, acc_j)`; `partial`
  iff `reporting_count >= 1` and not all together, or exactly one reporting member
  while others are stale (names it); `unknown` iff `reporting_count == 0`.
- `note` always populated.
- Tests `cli/tests/groups/test_presence.py` (≥ 20): three at school → `all_together`;
  shoes 2 km away → `partial`, diverged=[shoes]; backpack stale 4 h, shoes+bike
  together → `all_together` with stale=[backpack] and the note names it; all stale →
  `unknown`, never "at home"; single-member group never `all_together`.

**E5-T3 (M) Quorum `groups/quorum.py`** (D19). `evaluate_group_crossings(session,
event)`: per group of the device, gather member events for the same place and type
within `group_window_minutes` (30); quorum `any|majority|all|<int>` over non-stale
members; emit one `group_place_events` row per (group, place, type, window),
idempotent; confidence capped at `medium` when any member is stale; note names them.
Tests `cli/tests/groups/test_quorum.py`: majority with one stale member; `all` never fires
while any member is stale; duplicate device events do not double-fire; window expiry.

**E5-T4 (M) API `api/routes_groups.py`:** `GET/POST /api/groups`, `PUT/DELETE
/api/groups/{id}`, `PUT /api/groups/{id}/members`, `GET /api/groups/{id}/presence`,
`GET /api/groups/events`; `GET /api/timeline?group_id=` returns per-member tracks
(test asserts separate `device_id` arrays and no cross-device hop, invariant 5).
Tests `cli/tests/test_api_groups.py`.

**E5-T5 (S) CLI `findplus groups list|add|remove|members|presence|events`**
(`presence` prints verdict, a `stale` column and the note). Tests.

**E5-T6 (S) Commit** `feat: device groups with partial-presence logic`.

### E6 — Alerts

**E6-T1 (S) Credential store `alerts/store.py`.** `~/.findplus/alerts.json` 0600:
`{"channels": {"telegram": {bot_token, chat_id, chat_title}, "webhook": {url,
secret}}}`. `logging_setup._SENSITIVE_KEYS` += `bot_token`, `chat_id`, `webhook_url`,
`secret`; token regex `\d{8,10}:[A-Za-z0-9_-]{35}` added to `_TOKEN_PATTERN`. Tests:
file mode; redaction.

**E6-T2 (M) Channel protocol + Telegram `alerts/channels/telegram.py`.**
`send(text) -> DeliveryResult` with 10 s timeout, one retry on 5xx, typed errors for
401/403/400. `telegram_setup(token, wait_seconds=120, poll=2)`: `getMe` validates the
token and returns the bot username; loop `getUpdates?offset=`; instruct "open
t.me/<bot>, press Start or send any message"; capture the first chat id (private or
group; report the type); store; send "Find+ connected ✓". On **409 Conflict** explain
that a webhook is set on this bot and stop; never call `deleteWebhook`. Tests
`cli/tests/alerts/test_telegram.py` with a mocked transport: happy path, 409, bad token,
timeout.

**E6-T3 (S) Webhook channel `alerts/channels/webhook.py`.** JSON POST `{event,
place, group, devices, observed_at, fetched_at, lag_minutes, confidence, note}` with
optional `X-FindPlus-Signature` (HMAC-SHA256). Tests with a loopback `http.server`.

**E6-T4 (M) Rules and dispatch.** Tables `alert_rules(id, place_id NULL, group_id
NULL, device_id NULL, on_enter, on_exit, channel, cooldown_minutes DEFAULT 30, enabled,
also_notify_members BOOL DEFAULT 0)` and `alert_deliveries(id, rule_id, event_kind,
event_id, sent_at, status, error)` (in migration 0005). `dispatch.process(events)` is
called by the poller **after** the ingest transaction commits: match rules, cooldown
per (rule, place, subject), de-dup per event id, message includes observed time,
reported time and lag, record delivery; group rules consume `group_place_events`,
device rules `place_events`; a group rule suppresses member rules unless
`also_notify_members`. Failures never crash the poller. Tests
`cli/tests/alerts/test_dispatch.py`: 200-event flapping fixture → one message; suppression;
failure recorded; lag in text.

**E6-T5 (M) API `api/routes_alerts.py`:** `GET /api/alerts/channels` (masked), `PUT
/api/alerts/channels/telegram`, `POST /api/alerts/channels/telegram/setup?wait=120`
(long-poll), `PUT /api/alerts/channels/webhook`, `POST /api/alerts/test`,
`GET/POST/PUT/DELETE /api/alerts/rules`, `GET /api/alerts/deliveries`. Tests incl.
masking and 401.

**E6-T6 (S) CLI `findplus alerts telegram-setup|webhook-set|test|rules list|add|remove|deliveries`.**
Hidden token prompt or `--token`. Tests.

**E6-T7 (S) Privacy text:** outbound calls are OSM tiles (browser), the location
networks (polling), and `api.telegram.org` / the user's webhook **only when
configured**. Wiki "Places & alerts" states WhatsApp-native is planned for v1.1 and the
webhook is the interim path (D9).

**E6-T8 (S) Commit** `feat: geofence alerts via Telegram and webhooks`.

### E7 — Service management (W3; files disjoint from E3)

**E7-T1 (M) `start|stop|restart|status|uninstall` (D8, D15).** P2's E7-T1 supersedes D15's two-invocation
start flow: one run now discovers, tracks and installs, and an unauthenticated `start` exits 4 (see
`.claude/phases/current/p2/specs/service-and-settings.md` § 1). Plan-text snapshot tests (launchd plist, systemd
unit + timer, schtasks XML); fake manager backend records calls; a test asserts every written path starts
with `$HOME`.
**E7-T2 (M) Windows watchdog (D13).** `schtasks /Create /SC MINUTE /MO 5 /TN FindPlusWatchdog …`; task XML
written to `~/.findplus/FindPlus-task.xml`; symmetric uninstall; `detect_manager()` test on Windows.
**E7-T3 (S) Watchdog port mismatch.** If `daemon.json` reports a different port, log
`watchdog_port_mismatch` and probe that port; 401 stays healthy.
**E7-T4 (M) `findplus doctor [--repair] [--json]`.** Checks and repairs per PLAN §4 E7 (python, perms,
DB head, providers, units, port, Chrome, alerts.json, `/Applications/Find+.app`).
**E7-T5 (S) `serve` refuses a second daemon** (exit 3 with the URL) using `daemon.json` + health probe.
**E7-T6 (S) SIGTERM handling**: poller thread stops, `daemon.json` removed; subprocess test.
**E7-T7 (S) `--program PATH` override** for units installed by the desktop app (E13-T5) + commit
`feat: complete user-level service management`.

### E8 — API + CLI completion (W5)

**E8-T1 (S) Lock sweep test.** Parametrised over every registered route: each non-`_PUBLIC` route returns
401 while locked, so new routes are covered automatically.
**E8-T2 (M) `GET /api/version`, `GET /api/widget`, status fields, config notices** exactly per
`specs/api-contract.md` and `specs/honesty.md`.
**E8-T3 (S) `findplus export --group` and `/api/export?group_id`** (one track per member; CSV with
`device_id`; never merged). Test.
**E8-T4 (M) OpenAPI tags + drift scripts** `packaging/scripts/gen-api-docs.py`, `gen-cli-docs.py`
rendering `.github/wiki/API-reference.md` and `CLI-reference.md`; CI fails on drift.
**E8-T5 (S) `findplus version --check`** + commit `feat: version, widget and status endpoints`.

### E9 — MCP server (D16)

**E9-T1 (S) SDK check.** Confirm `mcp` 2.2.0's high-level server API
(`FastMCP` or its successor) before writing code; record the import path in the
ticket.

**E9-T2 (M) Read tools `mcp/tools_read.py`:** `list_devices`, `list_groups`,
`list_places`, `get_latest(device_id?)`, `get_timeline(day, device_id?, group_id?)`,
`get_place_events(...)`, `get_group_presence(group_id, window_minutes=60)`,
`get_status`, `export(format, start, end, device_id?)` (text, capped at 5 MB with a
truncation flag). Every response includes the honesty note from `/api/config`.

**E9-T3 (S) Write tools `mcp/tools_write.py`** only with `--allow-writes`:
`poll_now`, `add_place`, `remove_place`, `add_group`, `set_group_members`, `lock`.

**E9-T4 (M) Lock handling.** `unlock(pin)` keeps a session cookie in the MCP
process; `FINDPLUS_PIN` honoured at startup; while locked every tool returns
`{"locked": true, "hint": "call unlock"}`. Tests `cli/tests/mcp/test_server.py` with the
SDK's in-memory client against a `TestClient`-backed daemon: locked → hint; unlocked →
data; writes absent without the flag; daemon down → clear error.

**E9-T5 (S) `findplus mcp [--allow-writes] [--url]`** + wiki page with Claude
Desktop / Claude Code config snippets. Commit `feat: MCP server over the local API`.

### E10 — Web UI (S1 in W6: places, groups, providers · S2 in W7: alerts, screenshots)

**E10-W6-S1-T1 (L) Places UI:** circles by colour; "Add place" dialog with click-to-place crosshair mode;
edit/delete; radius slider with live circle; advanced confirmation counts; presence chip per device row.
**E10-W6-S1-T2 (M) Groups UI:** group selector beside the device filter; per-member coloured overlays with
legend; presence panel with verdict, together/diverged/stale lists and the note verbatim; stale members get a
grey "no fix for N h" badge and no marker.
**E10-W6-S1-T3 (S) Provider badge** on device rows and in the Devices picker; Apple rows say "Apple Find My
(keys you hold)".
**E10-W6-S1-T4 (S) Honesty text** from `specs/honesty.md` rendered from `/api/config.notices`;
`cli/tests/test_honesty_text.py`.
**E10-W6-S1-T5 (M) Playwright tests** `cli/tests/ui/test_places.py`, `test_groups.py`, `test_lock.py` (moved).
**E10-W7-S2-T1 (M) Alerts tab:** masked token field; "Connect" runs the setup flow with a live status line;
"Send test"; webhook URL/secret; rules table; one latency disclaimer; "Show map in widget" toggle with its
privacy sentence.
**E10-W7-S2-T2 (M) Playwright tests** `cli/tests/ui/test_alerts.py` (token masked; rule CRUD; disclaimer present).
**E10-W7-S2-T3 (M) Real screenshots.** `packaging/scripts/screenshots.py` seeds a demo DB, starts
`serve --no-poller` on a random port, drives Playwright at 1440×900 light and dark: dashboard, day timeline,
places dialog, group presence, alerts settings, lock screen → `.github/docs/screenshots/*.png` (≤ 400 KB each).
**E10-W7-S2-T4 (S) Commit** `feat: places, groups and alerts in the dashboard`.

### E11 — Apple provider (D10, D11)

**E11-T1 (S) Extra** `apple = ["findmy>=0.10,<0.11"]`; `is_available()` returns
`(False, "pip install 'findplus[apple]'")` on ImportError.

**E11-T2 (M) Auth `providers/apple_findmy/auth.py`.** `AppleAccount` with
`LocalAnisetteProvider` by default or `RemoteAnisetteProvider(FINDPLUS_APPLE_ANISETTE_URL)`;
terminal prompts for Apple ID + password (never stored); 2FA via trusted device or
SMS; account state serialised to `~/.findplus/apple-account.json` 0600 and restored on
start. `findplus auth --provider apple-find-my`. Tests with a fake account class:
round-trip, 2FA path, expired state → `AuthRequiredError`.

**E11-T3 (M) Accessories `providers/apple_findmy/accessories.py`.** `findplus apple
add-accessory NAME --plist PATH | --private-key B64`; stored under
`~/.findplus/apple/<id>.json` 0600; `device_id = "apple:" + sha256(pubkey)[:24]`.
Tests: id stability; bad key rejected.

**E11-T4 (M) `locate()`** → `fetch_last_reports(accessory)` → `RawObservation`s
(tz-aware `observed_at`, `fetched_at = now`, confidence mapped to metres and
documented as approximate, `source="apple-find-my"`); full batch retained. Tests with
fixture reports; dedup holds across providers.

**E11-T5 (S) Honesty surfaces** in README, wiki Providers page and UI (keys you hold;
DIY tags work; AirTags need pairing keys most users cannot extract; account risk).

**E11-T6 (S) Commit** `feat: Apple Find My provider (optional extra)`. If the epic
overruns two working days: ship E11-T1 plus the not-installed message and state it in
the README.

### E12 — CLI distribution (W5)

**E12-T1 (M) PyPI readiness + TestPyPI job.** `python -m build --outdir dist cli`; `twine check`; clean-venv smoke on macOS and
Linux CI; TestPyPI rehearsal job in `release.yml` (environment `testpypi`, no approval).
**E12-T2 (M) `install.sh`** per `specs/packaging-and-release.md` § install.sh contract; shellcheck; CI run on
ubuntu and macos with `FINDPLUS_WHEEL`.
**E12-T3 (M) Homebrew formula template** `packaging/homebrew/findplus.rb.tmpl` + `packaging/scripts/gen-formula.sh`
(`brew update-python-resources`); local `brew install --build-from-source ./findplus.rb` + `brew test`.
P2-E7-W2-S1-T3 changed the caveats last line to `findplus setup`, matching install.sh's new final line.
**E12-T4 (S) README install section** (three paths + dmg; two first-run commands; no inline comments).
**E12-T5 (S) `packaging/scripts/bump-version.sh`** (refuses on a dirty tree; owner-run only).
**E12-T6 (S) `packaging/scripts/release-local.sh`** skeleton: Python steps (build, twine check, TestPyPI
upload) with the macOS steps stubbed as named functions filled by E13-T6/E16-T5.
**E12-T7 (S) Commit** `build: PyPI, curl installer and Homebrew formula`.

### E13 — macOS app (Tauri shell, PyInstaller sidecar)

**E13-T1 (M) Decision record** in ARCHITECTURE § Desktop: Tauri 2, no JS build,
static splash in `desktop/ui/`, main window created from Rust with
`WebviewUrl::External("http://127.0.0.1:8647/")` after health; sidecar = PyInstaller
**onedir** `findplus-daemon` (onefile rejected: extracts ~150 MB per launch and
complicates library validation); tray via the `tray-icon` feature; status dot via
`IconMenuItem` with four PNGs; fallback coloured `●` in text.

**E13-T2 (L) PyInstaller spec `packaging/pyinstaller/findplus-daemon.spec`.** Entry
`findplus.cli.main:main`; datas: `web/static`, `db/migrations`,
`_vendor/GoogleFindMyTools`; hidden imports for uvicorn, alembic, protobuf; excludes
tests, playwright, frida. Output to
`desktop/src-tauri/binaries/findplus-daemon-<target-triple>/`. Smoke script
`packaging/scripts/sidecar-smoke.sh`: from `/tmp`, `serve --no-poller` health OK, `db
upgrade` OK, `doctor` OK.

**E13-T3 (L) Tauri project `desktop/src-tauri/`.** `Cargo.toml` (tauri 2.11
`tray-icon`, `image-png`; plugins shell, single-instance, positioner),
`tauri.conf.json` (`productName: "Find+"`, identifier `com.acamarata.findplus`,
`bundle.targets: ["app","dmg"]`, `externalBin`, `minimumSystemVersion: "13.0"`,
`signingIdentity` from env, entitlements), `src/main.rs`, `src/daemon.rs` (health →
LaunchAgent detection → kickstart, else spawn child `serve --foreground`; kill child on
exit), `src/status.rs` (poll `/api/status` every 45 s → `Green|Amber|Red|Grey`),
`src/tray.rs`, `src/windows.rs`. Rust unit tests for the status mapping and the
never-two-daemons decision table.

**E13-T4 (M) Tray menu** exactly: `[dot] Polling normally · last poll 2 min ago`
(disabled) → `Latest: Bike seen 14 min ago near Home` (hidden when locked) → `Tracked
devices: 3` → `Poll Now` (disabled when locked or daemon down) → `Lock` → `Open
Dashboard` → `Settings…` → separator → `Open App` → `Quit`. Colours: green
`ok && last_poll_age < 2×interval`; amber stale or daemon not answering; red
`last_error_type in {auth, decrypt}` or `consecutive_failures >= 3`; grey on 401.
Quit with a child sidecar → confirm "Polling stops when Find+ quits. Install the
background service instead?" with a button that runs `findplus start --yes` via the
sidecar.

**E13-T5 (M) "Start at login" toggle** installs the same LaunchAgent with
`ProgramArguments` pointing at `/Applications/Find+.app/Contents/MacOS/findplus-daemon
serve --foreground` plus the watchdog, through the Python service code (one
implementation). Test: plan text contains the app path.

**E13-T6 (L) Signing and notarisation.** `packaging/scripts/sign-sidecar.sh` signs
every Mach-O in the onedir, innermost first, `--options runtime --timestamp
--entitlements packaging/entitlements.plist` (`allow-unsigned-executable-memory`,
`disable-library-validation`, `allow-dyld-environment-variables`). Then `cargo tauri
build` signs the outer bundle and notarises when `APPLE_API_KEY`, `APPLE_API_KEY_ID`,
`APPLE_API_ISSUER` are set; `xcrun stapler staple`. Verify `spctl -a -vv --type
install Find+.app` and `codesign --verify --deep --strict`. Local builds use the
keychain identity. CI needs the `.p12` secret (owner). Fallback documented: unsigned
build with right-click → Open, never called a clean install.

**E13-T7 (M) DMG.** Tauri dmg with background and `/Applications` symlink; `hdiutil
verify`; size budget ≤ 120 MB, actual size recorded in release notes.

**E13-T8 (M) Runtime edge cases:** CLI daemon of a different version on the port →
attach and show both versions; daemon crash → amber and a "Restart daemon" item; lock
→ grey; Chrome missing → "Sign in" item opens help. Rust tests for the decision table;
manual checklist in the wiki.

**E13-T9 (S) Icons:** app icon set from `icon.svg` via `cargo tauri icon`; tray
template icon (`iconAsTemplate=true`) plus four dot PNGs @1x/@2x.

**E13-T10 (M) Intel Macs:** second artefact from `macos-13` if the runner exists;
otherwise arm64-only and say so.

**E13-T11 (S) Commit** `feat: Find+ macOS menu-bar app`.

### E16 — macOS widget (WidgetKit, W7; spec `specs/widget.md`, D21)

**E16-T1 (M) Xcode project** `desktop/widget/FindPlusWidget.xcodeproj` with target `FindPlusWidgetExtension`
(appex, Swift 5.10, macOS 14.0, bundle id `com.acamarata.findplus.widget`, App Sandbox + network.client
entitlements), a `Tests` target, and `desktop/widget/README.md`.
**E16-T2 (M) Model + timeline provider.** Codable mirror of `/api/widget`; `URLSession` fetch with 3 s timeout;
entries for ok/stale/error/locked/down; policy `.after(now + 15 min)`.
**E16-T3 (L) Views** for systemSmall/Medium/Large per the spec, dark mode, age formatting, stale rendering,
footer notice, optional `MKMapSnapshotter` when `show_map`.
**E16-T4 (M) App Intents** "Poll now" (POST /api/poll-now; disabled when locked/down) and "Open Find+"
(`findplus://open`).
**E16-T5 (L) `packaging/scripts/embed-widget.sh`**: copy the appex into `Find+.app/Contents/PlugIns/`, sign
inner-to-outer, re-notarise, staple, rebuild the dmg; verify with `pluginkit -m` and `spctl`.
**E16-T6 (M) `reload-widgets` helper + app hook + `findplus widget show-map|refresh`.** The Tauri app calls
the helper after each `/api/status` poll that changes `last_poll_at`; `findplus://refresh-widget` handled.
**E16-T7 (M) Swift tests + manual checklist** (`ModelTests`, `ProviderTests`; wiki macOS-app page checklist:
gallery three sizes, locked state, intents, dark mode).
**E16-T8 (S) Commit** `feat: Find+ widget`.

### E14 — Repository, docs, CI, release

**E14-T1 (S) Create `acamarata/findplus` and `acamarata/homebrew-tap`** (public,
GPL-3.0-or-later, description, topics `find-hub`, `find-my`, `location-history`,
`geofence`, `telegram`, `tauri`, `fastapi`, `sqlite`, `mcp`). Owner-gated
(`PROMPT.md` §10 item 1). First push only after E14-T10. Branch protection: PR
required, CI required, no force-push.

**E14-T2 (M) `ci.yml`.** Jobs: `lint` (ruff, `node --check` on every JS file,
`shellcheck install.sh`, `lint-prose.sh` on README); `test` matrix `{ubuntu-latest,
macos-latest} × {3.12, 3.13}` plus `3.14` `continue-on-error`; `windows-latest ×
3.12` unit tests without browser tests; `browser` on macOS with `playwright install
chrome`; `wheel-smoke`; `sidecar-smoke` on macOS; `cargo test` + `clippy`; coverage
via `pytest-cov` to Codecov (`fail_ci_if_error: false`, per the acamarata CI
standard) with the 95 % floor for the four engine modules enforced by `coverage
report --fail-under` on that subset.

**E14-T3 (M) `release.yml`.** Trigger tag `v*`: `build-python` → `publish-pypi`
(trusted publishing, environment `pypi` with required approval) → `build-dmg`
(macos-latest arm64; `.p12` from secrets, sidecar build, sign, `cargo tauri build`,
notarise, staple; upload `FindPlus-<ver>-aarch64.dmg` + `.sha256`) → `github-release`
(draft from the CHANGELOG section; attaches dmg, wheel, sdist, `install.sh` with the
pinned version) → `update-tap` (PR on the tap with new URL/sha256 and regenerated
resources; needs `TAP_PUSH_TOKEN`). `packaging/scripts/release-local.sh` reproduces
every step on the owner's Mac.

**E14-T4 (S) `screenshots.yml`** (`workflow_dispatch`): regenerates screenshots on
macOS and opens a PR.

**E14-T5 (L) Wiki `.github/wiki/`:** Home, Install, First-run, Devices-and-groups,
Places-and-alerts, App-lock, Privacy-and-threat-model, macOS-app, CLI-reference
(generated by `gen-cli-docs.py`, drift-checked in CI), API-reference (from the OpenAPI
schema, drift-checked), MCP, Providers, Troubleshooting (Chrome closed by auth; 409 on
Telegram; port in use; Gatekeeper; "why is my alert 40 minutes late"), FAQ,
Contributing. `wiki-sync.yml` per the acamarata standard.

**E14-T6 (M) README.** What it is / is not (Find Hub notice verbatim), screenshots,
install (three paths + dmg), first run (two commands), features with the Apple parity
caveat, privacy, honesty box (latency, lock ≠ encryption, FileVault, stale ≠ home),
CLI/API/MCP pointers, licence and attribution (GoogleFindMyTools GPL-3.0, FindMy.py
MIT, Leaflet BSD-2), "not affiliated with Apple or Google". `lint-prose.sh` bans the
listed words and runs in CI.

**E14-T7 (S) Community files:** `CONTRIBUTING.md`, `SECURITY.md` (private reporting
via GitHub advisories; threat-model summary), `CODE_OF_CONDUCT.md` (Contributor
Covenant 2.1), issue templates (bug, feature, provider request), PR template with the
gate checklist, `dependabot.yml` (pip weekly grouped, cargo weekly grouped, actions
monthly).

**E14-T8 (S) Licence files:** root `LICENSE` GPL-3.0-or-later; vendor LICENSE
untouched; `.github/docs/THIRD-PARTY.md` generated by
`third-party-licenses.py` (`pip-licenses`).

**E14-T9 (S) `CHANGELOG.md` 1.0.0 entry.**

**E14-T10 (S) Pre-push self-check:** root listing; old-name grep empty; no
`Co-Authored-By`; `gitleaks detect` clean; planning docs under `.github/docs/`;
`grep -rn "Find My+"` empty.

### E15 — QA & Done, owner handoff

**E15-T1 (M) Full gate run** on macOS and Linux (Docker `python:3.12` for Linux):
pytest including browser tests, ruff, node, shellcheck, wheel smoke, sidecar smoke,
cargo test/clippy, `brew install` from the tap PR, `install.sh` in a temporary `HOME`.

**E15-T2 (M) Three review loops** (owner's five-step flow): CR per epic → fixes → QA
re-run; then a blind adversarial pass over geofence, presence, alerts and lock asking
"where can this state something about a child's location that the data does not
support?".

**E15-T3 (S) Screenshot verification** of every state in E10-T8 plus the tray menu in
all four colours (drive the app against a fake `/api/status` fixture server and
`screencapture` the menu).

**E15-T4 (S) Fresh-machine rehearsal** in a new macOS user account: `brew install
acamarata/tap/findplus` → `findplus auth` (stops at the Google login, owner-only) →
`findplus doctor`; then the dmg: Gatekeeper accepts, tray appears, "Open App" shows the
dashboard, quitting leaves no second daemon.

**E15-T5 (S) Handoff report** per `PROMPT.md` §8 with exact commands (no inline
comments) and the proven/unproven split.

**E15-T6 (S) Version, tag, publish** — owner-gated: `v1.0.0` after approval; PyPI via
the approval environment; dmg attached; tap PR merged.

---

## 5. Test plan summary (existing suite stays green throughout)

| Area | Files | Approx. new cases |
|---|---|---|
| Packaging/config | `test_config_and_logging.py`, `test_cli_config.py`, `test_migrations.py`, `test_wheel_install.py` | 18 |
| Providers | `cli/tests/providers/test_registry.py`, `test_google_findhub.py` (moved), `test_apple_findmy.py` | 25 |
| Poller | `test_poller.py` | 6 |
| Geofence | `cli/tests/places/test_geofence.py`, `test_ingest_hook.py`, `test_repo.py` | 40 |
| Groups | `cli/tests/groups/test_presence.py`, `test_quorum.py` | 35 |
| Alerts | `cli/tests/alerts/test_telegram.py`, `test_webhook.py`, `test_dispatch.py`, `test_store.py` | 30 |
| API | `test_api_places.py`, `test_api_groups.py`, `test_api_alerts.py`, `test_api_providers.py`, lock sweep | 45 |
| CLI | `test_cli_{places,groups,alerts,service,config}.py`, help snapshot | 30 |
| Service | `test_service.py`, `test_service_cli.py`, `test_watchdog.py` | 25 |
| MCP | `cli/tests/mcp/test_server.py` | 12 |
| UI (Playwright) | `cli/tests/ui/test_{lock,places,groups,alerts}.py` | 14 |
| Static/honesty | `test_static_assets.py`, `test_honesty_text.py` | 6 |
| Rust | `desktop/src-tauri/src/*` | 10 |
| Shell | shellcheck + CI run of `install.sh` | 2 jobs |

Target: 262 + ≈ 300. Coverage floor 95 % lines for `geofence.py`, `presence.py`,
`quorum.py`, `dispatch.py`. Every test: no real account, `HOME` monkeypatched, an
autouse fixture blocks non-loopback sockets. `cli/tests/INVARIANTS.md` maps each of the
twelve invariants to the test ids that guard it.

---

## 6. Acceptance checklist for "done"

1. `pytest -q` green on macOS 3.12/3.13, Linux 3.12/3.13, Windows 3.12 (unit);
   browser tests green on macOS.
2. ruff check/format, `node --check`, shellcheck, `cargo clippy -D warnings`,
   `cargo test` clean.
3. Every invariant has a passing test listed in `cli/tests/INVARIANTS.md`.
4. `pipx install findplus` from TestPyPI → `findplus doctor` green on a clean macOS
   user and a clean Ubuntu container.
5. `curl … install.sh | bash` → same; re-run is a no-op; `--uninstall` leaves nothing.
6. `brew install acamarata/tap/findplus` → `brew test findplus` passes.
7. `FindPlus-1.0.0-aarch64.dmg` passes `spctl -a` on a machine that never saw the
   certificate; tray shows four states; "Open App" shows the dashboard; quitting
   leaves one daemon at most.
8. Wiki pages exist for all 14 topics; CLI and API references generated and
   drift-checked.
9. README screenshots are real PNGs from `screenshots.py`.
10. Root clean; old-name grep empty; no AI attribution; `gitleaks` clean; no "Find My+".
11. Honesty sentences present in README, UI (test-enforced) and wiki.
12. Handoff report delivered with the unproven items named.

---

## 7. Risks

| # | Risk | Sev | Lik | Mitigation | Ticket |
|---|---|---|---|---|---|
| R1 | Live Google path unproven (auth, FCM push, decryption). [Certain] | High | Med | Fixture-verified; owner runs `findplus auth` at handoff; `--debug-protobuf` redacted dump so the first failure is diagnosable in one round-trip. | E15-T5, E3-T2 |
| R2 | `undetected-chromedriver` 3.5.5 (2023) vs current Chrome; `pkill -f chrome`. [Likely] | High | Med | Pin; document; `doctor` checks Chrome; keep the warning. | E7-T5 |
| R3 | PyInstaller under hardened runtime + notarisation. [Likely] | High | Med | Per-Mach-O signing, entitlements, `spctl` in CI; documented unsigned fallback. | E13-T6 |
| R4 | Two daemons or two writers on 8647 / the DB. | Med | Med | Health probe + `daemon.json` + bind failure; WAL; app attaches rather than spawns. | E2-T4, E13-T3 |
| R5 | False EXIT for a child still at school. | High | Med | Hysteresis band, two exit confirmations, low-accuracy fixes ignored, jitter tests, confidence in every alert. | E4-T2 |
| R6 | "Left behind" reported for a stale tag. | High | Low | `stale` first-class; verdicts exclude stale; mandatory note; adversarial pass. | E5-T2, E15-T2 |
| R7 | Alert storms. | Med | Med | Cooldown + de-dup + 200-event test. | E6-T4 |
| R8 | Telegram 409 / group privacy mode. | Low | Med | Detect and explain; never touch the user's webhook. | E6-T2 |
| R9 | FindMy.py 0.x API churn, 2FA friction, Apple account action. | Med | High | Optional extra, lazy import, `<0.11` pin, honest docs, Google-only fallback. | E11 |
| R10 | Homebrew formula with ~40 resources drifts per release. | Med | High | Regenerate in the release workflow; `brew test` in CI; pipx documented as fallback. | E12-T3 |
| R11 | Windows never run on real Windows. | Med | High | Unit-tested plans + Windows CI; "community-tested" label. | E7-T3 |
| R12 | 300-line-cap refactors regress behaviour. | Med | Med | Route-table and help snapshots; browser tests; own commits. | E8-T1/T4, E10-T1 |
| R13 | `mcp` 2.x API differs from 1.x examples. | Low | Med | Verify first (E9-T1); low-level `Server` fallback. | E9-T1 |
| R14 | Protobuf 7.x vs vendored `_pb2` from 5.x (passing today). | Low | Low | Pin `protobuf>=5.28,<8`; import-all test. | E3-T2 |
| R15 | Intel runner retirement → no x86_64 dmg. | Low | Med | arm64-only with a note. | E13-T10 |
| R16 | Prose lint false positives. | Low | Med | Fail for README, warn for wiki. | E14-T6 |
| R17 | Heavy builds concurrently on 16 GB. | Med | Med | Serialise; E13 is the only heavy-compile lane. | dispatch |
| R18 | "Find+" is closer to "Find My" than "Waypost" was. [Guessing on legal exposure] | Med | Low | Owner's decision; nominative use only, no logos, "not affiliated" line, never "Find My+". | E14-T6, E14-T10 |

---

## 8. Unknowns (each with the default the plan takes)

| # | Unknown | Default |
|---|---|---|
| U1 | Whether the vendored protocol code works against a Moto Tag 2 on Google's current backend. | Unknown until the owner authenticates; reported as unproven. |
| U2 | `.p12` export for CI signing. | Local signed builds; CI signing once `APPLE_CERTIFICATE_P12_BASE64` exists. |
| U3 | PyPI trusted-publisher registration. | Release job gated; TestPyPI rehearsal first. |
| U4 | `IconMenuItem` PNG dots render as expected on macOS 27. [Likely yes] | Coloured `●` text fallback. |
| U5 | FindMy.py `fetch_last_reports` signature and confidence semantics in 0.10.2. | Verified at E11-T4 start. |
| U6 | Homebrew's tolerance for the resource-heavy formula in a personal tap. [Likely fine] | Resource-based formula; pipx fallback documented. |
| U7 | Intel-Mac demand. | arm64 first. |
| U8 | Whether the desktop app should install the LaunchAgent by default. | Opt-in toggle (installing background jobs silently contradicts the "print the plan first" rule). |
| U9 | Whether `Find+.app` (with `+`) causes any tooling friction (Tauri bundler, notarytool, dmg). [Guessing: none; `+` is legal in bundle names] | Keep `Find+`; if a tool chokes, product name `FindPlus` with display name `Find+` in `Info.plist` `CFBundleDisplayName`. |

---

## 9. Owner boundaries

Listed in `PROMPT.md` §10 (first push, publish, `.p12`, PyPI publisher, Google
sign-in). Everything else in this plan is decided.

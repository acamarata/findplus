# People and presence (design spec, Find+ 1.2 candidate)

Status: design, not built. Base `release/1.1.5` at `feb0b2f`. [Certain] = read in that code; [Likely] = strong
inference; [Guessing] = assumption to verify.

## 0. What the owner asked, and the short answer

| # | Ask | Answer in this spec |
|---|---|---|
| 1 | Group "Sam Bag/Bike/Shoes Red/Shoes White" by name | §2 naming suggestions, always previewed, never silent |
| 2 | Track the person, not one tracker | §3 inference: movement beats stillness, carry weights break ties |
| 3 | New places notify arrive and leave, Telegram, "Sam arrived at Grandma's" | §5 person events + default rule per place + one-click backfill |
| 4 | 4:17 here, 4:18 far away, 4:19 back: bad fix | §6 quality flags; today's filter misses this case (see §6.1) |
| 5 | Best durable format? | §9 SQLite in WAL is right; add backups, checks, restore, full export |
| 6 | "There 13:00 until 17:00", travel vs stay, Home is special | §7 day summary over the existing trips engine |
| 7 | Trackers left at school etc. | §4 left-behind state machine |
| 8 | Per-person day summary in app and Telegram | §7 API/CLI/MCP/digest, §8 Person page |

Pushback up front:
- "Sam has **just** left Home" overstates: alerts are often 10 to 40 minutes late (`honesty.ALERTS_LATENCY`).
  "Just" only when the sighting is under 10 minutes old at send time; otherwise the time (§5.4, Q2).
- Inferring one person from several trackers strains invariant 5 ("never merged across devices"). It holds only
  if the map keeps one line per tracker and every summary line names its tracker. This spec does both (Q1).

## 1. Data model

### 1.1 What is a Person: a group with `kind`

Decision: a Person is a row in `groups` with `kind = 'person'` (or `'pet'`), not a new `people` table.

Why [Certain]: groups already have members, name, colour, icon, presence (`groups/presence.py`), events
(`group_place_events`, `uq_gpe_dedup`), rules (`alert_rules.group_id`), dispatch (`GroupEvent`), export
(`group_export.py`) and day-story lanes (`trips_strip.js`). A new table duplicates all of it. Old groups become
`kind = 'set'` and behave exactly as today.

Rules: `set` keeps quorum events (D19) untouched. `person`/`pet` get person events (§5) instead and
`groups/events.py` skips them; rules keep their `group_id`, so converting a set keeps its rules. A device sits in
at most one person/pet group (any number of sets): API check in `groups/repo.py` plus a trigger (§1.4).

### 1.2 Tracker roles and carry weights

New nullable `devices.role` (NULL = guessed from the name, §2) and `devices.carry_weight` (NULL = role default).

| role | default weight | why |
|---|---|---|
| phone, watch, collar (pet) | 1.0 | worn or pocketed |
| wallet, keys | 0.8 | usually carried, sometimes left on a hook |
| shoes | 0.8 | worn, but kids own several pairs; the other pair stays home |
| bag, jacket | 0.5 | taken off and left often (the owner's own example) |
| bike, scooter | 0.4 | parked for hours; moving bike is strong evidence (motion factor, §3) |
| tablet, laptop | 0.4 | stays on a desk |
| car, luggage | 0.2 | moves with whoever drives or carries it |
| other | 0.5 | unknown accessory |

Per-tracker override 0.0 to 1.0 (0 = never used to place the person).

### 1.3 Place kinds

`places.kind`: `home | school | work | family | shop | other` (default `other`); several homes allowed. Home
stays fold into one line, left-behind alerts are off at homes (§4), the summary opens "Overnight at Home". The
dialog guesses kind from the name ("Grandma's" -> family) for the owner to confirm.

### 1.4 Migration `0013_people_and_quality`

Order inside one revision; `upgrade_to_head` already wraps it in `fk_disabled` [Certain, db/migrate.py].

```
groups               + kind TEXT NOT NULL DEFAULT 'set'        -- API-validated (no CHECK: no parent-table rebuild)
devices              + role TEXT NULL, + carry_weight REAL NULL
places               + kind TEXT NOT NULL DEFAULT 'other'
group_place_events   + basis TEXT NOT NULL DEFAULT 'quorum'    -- 'quorum' | 'person'
                     + note TEXT NULL                          -- person events store their sentence
                     + lead_device_id TEXT NULL                -- tracker whose crossing decided it
alert_rules          + all_people BOOLEAN NOT NULL DEFAULT 0   -- batch rebuild: CHECK becomes
                       (all_people=1 AND group_id IS NULL AND device_id IS NULL)
                       OR (all_people=0 AND ((group_id IS NULL) <> (device_id IS NULL)))
alert_deliveries     CHECK event_kind IN ('device','group','left_behind')   -- batch rebuild
person_place_states  (group_id FK groups CASCADE, place_id FK places CASCADE, state, since_observed_at,
                      pending_side, pending_since, last_transition_at, updated_at, PK(group_id, place_id))
left_behind          (id PK, group_id FK CASCADE, device_id FK devices CASCADE, place_id FK places SET NULL,
                      anchor_lat_e7, anchor_lon_e7, state, started_observed_at, confirmed_at, cleared_at,
                      clear_reason, notified_at, INDEX(group_id, device_id, state))
observation_quality  (observation_id PK FK location_observations CASCADE, score REAL, suspect BOOLEAN,
                      reasons TEXT, corroborated_by INTEGER NULL, algo_version INTEGER, computed_at)
                      INDEX(suspect)
digest_runs          (id PK, group_id FK CASCADE, local_date TEXT, channel, target, status, sent_at, error,
                      UNIQUE(group_id, local_date, channel, target))
trigger trg_one_person_per_device BEFORE INSERT ON device_group: RAISE(ABORT) when the new group is
  person/pet and the device already sits in another person/pet group
```

Risk: the two rebuilds. `alert_deliveries.rule_id` is `ON DELETE CASCADE` [Certain], so rebuilding
`alert_rules` with FKs on wipes the delivery log; 0008 did it safely under `fk_disabled`, and the migration test must assert
the delivery count survives. `groups` is deliberately not rebuilt. Downgrade drops everything new (lossy, as 0012).

New ORM classes go in `db/models_people.py`: `db/models.py` is 287 lines [Certain] and would pass the cap.

## 2. Naming auto-group (suggest, preview, accept)

Input: every visible device's display name (`labels.display_name`: label, else provider name).

1. Normalise: NFKC, casefold, strip diacritics for matching only; split on whitespace, `_ - . ( ) /`; turn
   possessives into the bare token (`Sam's` -> `sam`); keep original casing for display.
2. Classify tokens: role vocabulary (`pixel iphone galaxy phone mobile` -> phone; `watch fitbit` -> watch;
   `shoe shoes sneaker sneakers trainers boots` -> shoes; `bag backpack schoolbag satchel purse` -> bag;
   `key keys keyring` -> keys; `wallet`; `bike bicycle scooter`; `car van`; `jacket coat`; `ipad tablet tab`;
   `laptop macbook`; `suitcase luggage`; `collar` -> collar), modifiers (colours, `pro max plus ultra mini`,
   digits, `8a`-style model codes, ordinals), and candidate owner tokens (everything else, length >= 2).
3. Owner token: the first candidate token; a parenthetical `Bag (Sam)` or trailing `Bag Sam` also counts.
4. Cluster by exact owner token (after normalisation). No fuzzy matching: `Ali` and `Alia` stay apart.
5. Suggestion confidence: **high** owner token + role word ("Sam Bag"); **medium** owner token only
   ("Sam 2"); **low** the owner token is also a colour or brand ("Rose Bag", "Red Keys"), flagged in the preview.
6. Roles: the role word sets `devices.role` in the preview ("Sam Shoes Red" -> shoes).

Worked cases:

| names | suggestion |
|---|---|
| Sam Bag, Sam Bike, Sam Shoes Red, Sam Shoes White | Person "Sam": bag, bike, shoes, shoes (high) |
| Ali Pixel 8a, Ali Keys | Person "Ali": phone, keys (high) |
| Whiskers; Shadow | One token, no role word: "Is Whiskers a person or a pet?" (pet -> collar 1.0) |
| Pixel 11 Pro | No owner token: listed under "Whose is this?" with a person picker; role phone |
| Ali Pixel 8a twice | Both join Ali; `device_labels.unique_names` keeps them apart in text [Certain] |

Collisions: a same-named group (case-insensitive, like `groups/repo._name_taken` [Certain]) becomes "Turn group
Sam into a person". A device already in a person is never moved. Dismissals persist in setting `people.dismissed`.

Re-run: a new device row (`upsert_device` [Certain]) marks suggestions dirty; the dashboard then shows
"New tracker Sam Helmet looks like Sam's. Add it?" Nothing is grouped without a click.
`GET /api/people/suggestions` is a pure preview; `POST /api/people/suggestions/accept` takes the edited body.

## 3. Person location inference ("where is Sam now")

Pure function `people/infer.py: infer(members, now, params) -> PersonFix`. Inputs per member: last two
non-suspect fixes, role weight, place_states. No DB, no clock, tz-aware `now` (same contract as presence.py).

1. Drop members whose last fix is older than the group's `stale_after_minutes` (default 90, D18). They are
   listed as "no recent sighting", never placed (`honesty.PRESENCE_STALE`).
2. Score each reporting tracker: `s = weight x f_age x f_motion x f_acc`
   - `f_age`: 1.0 at 0 min, linear down to 0.3 at the stale limit.
   - `f_motion`: 2.0 "carried" when two consecutive non-suspect fixes in the last 6 h are more than
     `max(150 m, 2 x accuracy)` apart; 0.4 "parked" when it has not moved for 6 h; 1.0 when there are too few
     fixes to tell. **Trackers do not move on their own; a moved tracker was carried. A parked one proves little.**
   - Worked: Sam leaves at 7:40. Shoes Red carried 0.8 x 2 = 1.6; bag, bike, Shoes White parked at Home
     (0.5 + 0.4 + 0.8) x 0.4 = 0.68. B/R = 2.35, so `likely` away from Home. At School by noon the shoes still
     count as carried (moved within 6 h), so the answer stays `likely` at School.
   - `f_acc`: 1.0 at <= 100 m, 0.7 at <= 300 m, 0.4 beyond (missing accuracy = 100 m, as presence.py does).
3. Cluster reporting trackers with `presence._greedy_clique` (radius = group `cluster_radius_meters` plus
   accuracy) [Certain the function exists]. Repeat on the remainder to get every cluster.
4. Cluster score = sum of member scores. Best B, runner-up R (0 if none).
5. Confidence (plain words, never "is at"):
   - `likely`: B >= 2R and B >= 0.9. "Likely at School, seen 12 min ago (shoes, bike)."
   - `probably`: B >= 1.3R. "Probably near Home, seen 40 min ago (bag). Shoes say near the park."
   - `unsure`: otherwise. "Not sure: shoes near School, bag at Home."
   - `unknown`: nobody reporting. "No recent sightings. Last seen near Home at 4:10 PM."
6. Place: the saved place a confirmed `inside` place_state of a B member names; else "near <place>" when the
   centroid is within 500 m; else "an unnamed spot, 1.2 km from Home".

Output `PersonFix(confidence, place_id, lat, lon, accuracy_m, observed_at, supporters, dissenters, stale, text)`;
lat/lon is the lead tracker's own fix, never an average (invariant 12). Constants live in one `InferParams`.

## 4. Left-behind detection

States per (person, tracker): `with_person -> apart_pending -> left_behind -> cleared`, stored in the
`left_behind` table (non-`with_person` rows only). Enter `apart_pending` when all hold:
- the tracker's last non-suspect fix is still (no motion in its last 2 fixes) at anchor A;
- the person's best cluster excludes it, has confidence `likely`, and contains a tracker with weight greater
  than or equal to this one;
- the distance from A to the best cluster exceeds `max(300 m, place radius + exit_margin(radius))`
  (reuses `geofence.exit_margin` [Certain]);
- the tracker is not stale.

Confirm `left_behind` after `apart_minutes` (default 20) with the above true across at least two newer person
fixes. Hysteresis: one contrary fix resets `apart_pending`, never a confirmed row.

Alert once per episode. Setting `people.left_behind_alerts` (Q4): on at non-home places and unnamed spots, off at
`home` (a bike in the garage is normal). Sent on the channels of the rules that cover that person; logged in
`alert_deliveries` with `event_kind='left_behind'`. Text: "Sam's bag looks left at School. Last seen there at
3:02 PM; Sam's shoes were seen near Home at 3:40 PM."

Clear when the tracker moves (`carried`), the person's best cluster returns within the anchor radius (`rejoined`), the
tracker goes stale (`stale`, shown as "no recent sighting", never "still left behind"), or the owner taps
"I know" (`dismissed`, silences that tracker at that place for the rest of the local day).

False positives handled by construction: everyone asleep at Home or all at School: one cluster, no episode. Second pair of shoes: stays home, where
alerts are off; chip only. Sibling carries the bag: the bag moves, heavier trackers stay, so it is "moved without
Sam" (chip, no alert). Phone battery dies: it goes stale and drops out; what still reports places the person.

## 5. Person events (arrived / left)

### 5.1 Engine
`people/events.py`, a new post-ingest hook after the geofence and group hooks in
`ingest._run_post_ingest_hooks`, in its own SAVEPOINT like the others [Certain on the pattern]. For each
person/pet group the observation's device belongs to:

1. Skip suspect or held observations (§6). Skip when `observed_at <= person_place_states.since_observed_at`
   (the same backfill guard as `geofence.advance`).
2. Run `infer()` as of the observation's `observed_at`, using only fixes observed at or before it.
3. For each place: target side = `inside` when a supporter of the best cluster has a confirmed `inside`
   place_state there and confidence is `likely` or `probably`; `outside` when the person was inside and the best
   cluster's members have all left that place; otherwise no change (`unsure` never moves state).
   Trackers that never moved cannot move state: a change needs a supporter whose motion is not `parked`, or one
   with its own device ENTER/EXIT at that place since the person's last transition there. When the carried
   tracker goes quiet, the person holds where they were and the quiet tracker reads "no recent sighting".
   Likewise `infer()` answers `unsure` when its best cluster is all parked while another tracker (reporting or
   stale) moved within the window.
   `outside` comes only from a supporter's own device state `outside`: a supporter whose geofence still says
   `inside` holds the person there, so one stray fix never skips D17's two-exit confirmation. The event then
   carries the crossing time, the deciding tracker's first sighting on the new side (`people/crossing.py`).
4. Anti-flap: an opposite transition at the same place needs `settle_minutes` (default 10) since the last one.
   Device-level hysteresis (D17: 1 enter, 2 exit confirmations) has already filtered jitter underneath.
5. First evaluation seeds state with no event (D17's rule).
6. On a transition, insert one `group_place_events` row: `basis='person'`, `lead_device_id`, `confidence` high
   (likely) or medium (probably), counts filled honestly, `note` = evidence sentence. `uq_gpe_dedup` plus the
   window check in `groups/events._existing_group_event` make four trackers crossing produce one row.

Dispatch already picks up `notified_at IS NULL` group rows [Certain]; `_GROUP_EVENTS_SQL` adds `basis`, `note`, `g.kind`.

### 5.2 Rule matching
- `match()`: an `all_people` rule matches any `GroupEvent` whose group kind is person/pet.
- `suppressed_by_group()`: an enabled `all_people` or person rule suppresses device rules for that person's
  trackers at the same place and type unless `also_notify_members` (same semantics as today).
- Cooldown: default person rules use `cooldown_minutes = 0`. `in_cooldown` keys on (rule, channel, place) and
  ignores event type [Certain], so a 30-minute cooldown would swallow "left the shop" 20 minutes after "arrived".
  Debounce lives in the engine (§5.1.4). No quiet hours this release (Q5); dispatch is in `observed_at` order.

### 5.3 Default rule per place
`POST /api/places` gains `notify: bool = true`. When true, one rule is created in the same transaction:
name "Arrivals and departures at <Place>", `place_id`, `all_people=1`, `on_enter=on_exit=1`, cooldown 0.
Channel choice: exactly one of {telegram, whatsapp, webhook} configured -> that one; several -> telegram if
present, else all configured external ones; none -> `native` when the desktop app has registered, else the rule
is saved disabled with the hint "Connect Telegram to get these." The place dialog shows the checkbox ticked with
the chosen channel named. Backfill: the Alerts tab shows "3 places have no arrival alerts. Notify me" ->
`POST /api/places/notify-defaults` with a dry-run preview first (`?dry_run=1` lists the rules it would add).

### 5.4 Message templates (`people/messages.py`, through `web/locales/en.json` keys `people.msg.*`)
```
Sam arrived at Grandma's at 4:12 PM          (or "Sam just arrived at Grandma's" when < 10 min old)
Seen by Sam Shoes Red · reported 4:31 PM · 19 min late
Sam's bag stayed at Home.                    (only when a tracker is apart)
<honesty.ALERTS_LATENCY, verbatim, never truncated>
```
"Sam left Home at 7:40 AM" for EXIT. Times are local with the zone abbreviation, built by the existing
`dispatch_core._fmt_local_time` [Certain]. Probably-level events add "(probably; only the bag reported)".
`render_message` gets a `basis == 'person'` branch in a new `alerts/render_person.py` (dispatch_core is 290
lines [Certain]).

## 6. Bad-coordinate detection

### 6.1 Why today's filter misses the owner's case
`trips/outliers.py` drops a fix only when both legs exceed 55 m/s [Certain]. A 2.5 km 4:17/4:18/4:19 jump is
about 42 m/s per leg, so it is kept and drawn as a trip. It also only runs for trips; the geofence sees every fix.

### 6.2 Quality module `quality/` (pure rules + a store), replacing `trips/outliers.py` internals
Each observation gets `score` in [0, 1] and zero or more reasons:

| reason | rule (defaults) |
|---|---|
| `aba_teleport` | neighbours P, N within 30 min agree (`d(P,N) < 0.5 x min(d(P,X), d(X,N))`), `d(P,X) > max(500 m, 2 x (accP + accX))`, round-trip speed `(d(P,X)+d(X,N)) / (tN - tP) > 20 m/s` |
| `impossible_speed` | both legs above 55 m/s (today's rule, kept) |
| `edge_stray` | first/last fix of the window jumps away from two agreeing neighbours (today's rule) |
| `jump_unconfirmed` | ingest-time only: speed from the last trusted fix > 20 m/s and > 1 km, no next fix yet |
| `sibling_disagree` | 2+ other trackers of the same person, each seen within 10 min, agree within 300 m and this fix is > 1.5 km away while this tracker showed no motion before it |
| `low_accuracy` | accuracy > 1000 m (soft: score x 0.5, never suspect on its own) |
| `clock_skew` | `observed_at` later than `first_fetched_at` + 5 min |

`suspect = score < 0.5`. A suspect fix is rescued (`corroborated_by` = id) when another fix of the same tracker
within 15 min, or a sibling within 10 min, lies within `max(200 m, its accuracy)` of it. Reporter diversity:
Find Hub reports carry `source` (own_report, crowdsourced) [Certain] but no reporter id [Likely]; own_report fixes
get score x 1.1 (capped), so diversity is not used beyond that.

### 6.3 Storage and use
- Raw rows never change (invariant 8). Flags live in `observation_quality` with `algo_version`; a version bump or
  `findplus db recompute-quality [--since DATE]` rewrites them. Retention cascades through the FK.
- Ingest: the new fix and its predecessor are scored after insert. `jump_unconfirmed` holds the fix out of the
  geofence; the next fix either confirms it (clear the flag, feed both in order) or turns it into
  `aba_teleport`. Cost: an ENTER after a real fast trip can be one poll later. Accepted, documented.
- Stays, trips, person inference and left-behind skip suspect fixes. The trips payload keeps listing them under
  `outliers` with `reasons` added.
- UI: faint dot, dashed ring, tooltip "This sighting looks wrong: it jumps 2.4 km and back within 2 minutes.
  Left out of stays, trips and alerts." Toggle "Show sightings that look wrong" (on by default).

### 6.4 Test vectors (all synthetic, no network)
- V1 owner case: A 4:17 (x, y) acc 30; B 4:18 at 2.5 km acc 40; C 4:19 at 60 m from A. B = `aba_teleport`.
- V2 real drive: A home 8:00, B 3 km 8:06, C 6 km 8:12. Nothing flagged.
- V3 school run: home 7:40, school (3 km) 8:10, home 8:45. Nothing flagged: neighbours 65 min apart, ~1.5 m/s.
- V4 two bad fixes in a row: kept, both scored 0.6 (honest over clever, matches today's rule).
- V5 sibling disagree: shoes + watch at school 10:00 and 10:04; bag (still since 8:10) reports 3 km away at 10:02.
- V6 corroborated jump: B far, then C within 100 m of B two minutes later. B rescued.
- V7 ingest hold: B arrives alone; no ENTER at the far place; C confirms; one ENTER at C's time.

## 7. Daily summary

### 7.1 Algorithm (`people/day.py`, pure over loaded rows)
1. Local day bounds from `timeline.day_bounds_utc` (23/25 h DST days) [Certain].
2. Lines from person events of that day (`basis='person'`): "7:40 AM left Home", "8:10 AM arrived at School".
3. Lead-tracker stays of 15+ min outside saved places (existing `trips.segment`, non-suspect fixes): "10:05 to
   11:20 AM at an unnamed spot, 2.1 km from Home". Home visits fold into one line ("At Home 3:33 PM onward").
4. First line: "Overnight at Home" when the person state at local midnight is inside a `home` place with a
   non-stale fix; else "No sightings until 7:12 AM".
5. Last line: today and inside a place with a fresh fix -> "Still at School (seen 3:58 PM)"; stale -> "Last seen
   near School at 3:58 PM; nothing since". Never "still at" a place on stale data.
6. Gaps over 90 min outside a `home` place: "No sightings 11:00 AM to 1:30 PM."
7. Left-behind episodes: "Bag stayed at School from 3:00 PM."
8. Footer: "2 sightings looked wrong and were left out (show)." plus `honesty.TRIPS_APPROXIMATE`.
9. Every line carries `evidence` (tracker ids) and `confidence`; "around" prefixes a time when the supporting
   sightings are more than 10 min apart.

### 7.2 Surfaces
- API: `GET /api/people`, `GET /api/people/{id}/now`, `GET /api/people/{id}/day?date=&timezone=` ->
  `{person, date, timezone, now, lines[], left_behind[], suspect_count, gaps[], trackers[], label}`,
  `POST /api/people/{id}/day/send`. All 401 while locked.
- CLI: `findplus day <name> [--date] [--json]`, `findplus people list|suggest|accept|role`. MCP read:
  `list_people`, `where_is`, `get_person_day`; write (`--allow-writes`): `accept_people_suggestions` (D16).
- Telegram digest: setting `people.digest` `{enabled: false, time: "20:00", people: [ids], channel: auto}`.
  A `DigestScheduler` beside `RetentionScheduler` in `cmd_serve.py` [Certain on the pattern]; one `digest_runs`
  row per (person, local date, channel, target) so a restart never double-sends; held while locked
  (`honesty.ALERTS_LOCKED` posture).

## 8. UI: the Person page

Click a person's name anywhere (group card, lane, delivery log, widget): `#/person/<id>?date=YYYY-MM-DD`,
hash-routed like `#places` in `main.js` [Certain].

- Header: avatar (group icon + colour, letter fallback), name, the §3 now-status sentence, "seen N min ago".
- Date bar: prev/next arrows, date picker, "Today"; arrow keys move a day. Summary card: §7 lines, each focusing
  map and story on its moment.
- Map: one line per tracker (never merged), stays sized by dwell, suspect fixes faint. Day story: reuse
  `trips_view.js` lanes, lead tracker first.
- Trackers: role icon, name, weight, chip `carried` / `left at School` / `moved without Sam` /
  `no recent sighting`; tap to edit role or weight. Actions: Send today's summary, Notify me, Edit, Full map.
- States: loading, empty day, partial, error, locked (purge like `purgeStory()`), offline; 375/768/1280,
  light/dark, reduced motion, keyboard.

## 9. Durability assessment

Findings:
- WAL, `foreign_keys=ON`, `busy_timeout=10000`, `synchronous=NORMAL` on every connection [Certain, db/session.py].
- Alembic migrations, FK-safe rebuilds via `fk_disabled` [Certain]. Schema version = `alembic_version`.
- No backup, restore, `integrity_check`, `quick_check` or `foreign_key_check` in the package [Certain, grep].
- Exports cover observations only (CSV/JSON/GPX/KML) [Certain]; places, groups, rules and labels cannot leave.
- Retention: keep forever by default, daily pruner and `findplus prune` [Certain]. The DB lives on the boot disk
  in `~/.findplus` (D1); a Time Machine copy of a live WAL database can capture a mismatched file pair [Likely].
- Duplicates fill a NULL `accuracy_meters`/`battery_level` [Certain]: fill-only, so not strictly append-only.
- Volume [Guessing]: well under 1 M rows and a few hundred MB a year for 10 trackers. Easy for SQLite.

Recommendation: stay on SQLite in WAL. It is one file, transactional, crash-safe, needs no server, and suits a
local single-user daemon. Close these gaps:
1. `findplus db backup` via `sqlite3.Connection.backup` into `~/.findplus/backups/` (0600/0700), copy verified
   with `integrity_check`, rotated 7 daily + 4 weekly, run daily by the retention worker.
2. `quick_check` at daemon start; `integrity_check` + `foreign_key_check` in `findplus doctor` (new
   `cli/doctor_db.py`: doctor.py is at 300 lines [Certain]).
3. `findplus db restore <file>`: refuse while the daemon runs, verify the file, keep the current DB as
   `findplus.sqlite.replaced-<stamp>`, copy in, upgrade to head.
4. A failed quick_check makes the daemon read-only with a restore banner; the damaged file is never deleted.
5. `findplus db export --jsonl` / `import --jsonl`: every table, one object per line, header with schema
   revision and app version; import only into an empty DB, then upgrade. This is the human-readable escape hatch.
6. Derived data is recomputable: `observation_quality` (`recompute-quality`) and person states. A
   `findplus db rebuild-derived` replays observations through geofence and the person engine into fresh state,
   stamping every regenerated event `notified_at` so nothing re-sends.
7. `synchronous=FULL`: costs one extra fsync per commit; at a few commits per poll that is nothing. NORMAL in WAL
   can lose the last commits on power loss (no corruption). Fixes cannot always be fetched again, so FULL wins.

Do not: Postgres (a server for one user), Parquet/DuckDB as the store (no transactional upserts or FKs),
SQLCipher (FileVault covers disk theft, as `LOCK_NOT_ENCRYPTION` says), cloud sync.

## 10. Owner's live-instance setup plan (runs from their data, invents nothing)

1. Back up first (`findplus db backup`, new). Nothing touches the live DB before that.
2. Preview §2 over the real names. Expected from the request: Sam (4), Ali (2), Robin, Whiskers and Shadow as
   person-or-pet questions, "Pixel 11 Pro" under "Whose is this?". The owner accepts or edits.
3. Home: if a place named Home exists, set `kind=home`. If none, suggest the densest overnight dwell cluster
   (00:00 to 05:00 local, last 14 days, non-suspect fixes of the owner's phone-role trackers) with radius
   `max(100 m, 2 x median accuracy)` capped at 250 m, shown on the map for the owner to confirm. Coordinates come
   from the data only; nothing is typed in.
4. Suggested places: `trips.segment` stays over the last 30 days, clustered at 150 m, kept when visited on 3+
   distinct days for 30+ min, not inside an existing place. Each is a pin "Unnamed place, 9 visits, usually
   8:10 AM to 3:00 PM on weekdays. Name it?" Kind guessed from the pattern (weekday daytime -> school/work).
5. Default rules: for every place the owner names or confirms, the §5.3 rule; Telegram is chosen automatically if
   it is the only connected channel. Existing places get the backfill banner.
6. Digest off; the Person page offers "Send Sam's day to Telegram at 8 PM" as a one-tap opt-in.
7. Dry run: replay the last 7 days into scratch state and show the messages it would have sent, with a daily
   count (`alerts/dryrun.py` pattern [Certain]). The owner reads them, then turns alerts on.

## 11. Test plan (named synthetic scenarios, all offline, private `FINDPLUS_STATE_DIR`)

| name | proves |
|---|---|
| `sam_school_day` | 4 trackers home overnight, shoes+bag leave 7:40, arrive school 8:10, leave 15:00, home 15:33: exactly 4 person events, summary has those 4 lines |
| `bag_left_at_school` | bag stays at school, shoes go home: one `left_behind` at 15:20, one alert, cleared next morning when the bag moves |
| `sleeping_household` | all trackers still at Home 22:00 to 07:00: zero events, zero left-behind |
| `second_pair_of_shoes` | white shoes stay home daily: no alert (home default off), chip only |
| `sibling_carries_bag` | bag moves alone: no person EXIT, chip "moved without Sam" |
| `phone_dies` | phone stale at 11:00: still placed by watch; text names the stale phone |
| `four_trackers_one_arrival` | all 4 cross Grandma's within 3 min: one `group_place_events` row, one Telegram message |
| `owner_teleport_417` | V1: no ENTER/EXIT, no trip, flagged faint, summary footer counts 1 |
| `jitter_at_edge` | 40 alternating fixes at Home's edge (the D17 fixture): zero person events |
| `backfill_old_report` | a late older fix never moves person state; `dst_day`: summary on 23 h/25 h days |
| `naming_matrix` | every row of the §2 table, plus `Ali`/`Alia`, `Rose Bag`, existing group collision |
| `default_rule_channels` | 0/1/many channels configured -> disabled/that one/telegram |
| `migration_0013` | seeded 0012 DB with deliveries: upgrade keeps every row; downgrade then upgrade round-trips |
| `backup_restore` | backup while ingest writes; restored copy passes integrity_check and has the rows |
| `locked_person_page` | lock purges names, times and coordinates from the Person page DOM |
| `honesty_person_texts` | ALERTS_LATENCY and PRESENCE_STALE verbatim on every new surface |

## 12. Work split (order: P0, then A and B in parallel, then C, then D)

| pkg | owns (new unless marked) | depends |
|---|---|---|
| P0 schema | `db/migrations/versions/0013_people_and_quality.py`, `db/models_people.py`, small column adds in `db/models.py`, `db/models_alerts.py` (modified) | none |
| A quality + durability | `quality/{rules,score,store}.py`, `trips/outliers.py` (becomes a wrapper), ingest hold hook (one call in `ingest.py`), `db/backup.py`, `cli/cmd_db.py` (modified), `cli/doctor_db.py`, `service/retention.py` (backup call) | P0 |
| B people engine | `people/{naming,roles,infer,events,left_behind,messages,repo}.py`, `groups/events.py` (skip person kinds), `alerts/render_person.py`, `alerts/dispatch_core.py` + `dispatch_events.py` (match, suppress, loader), `api/routes_places.py` (`notify` + backfill) | P0; reads A's `is_suspect()` through an interface stub until A lands |
| C day + delivery | `people/day.py`, `api/routes_people.py`, `cli/cmd_people.py`, `mcp/tools_people.py`, `service/digest.py`, `cmd_serve.py` (one worker line) | B |
| D UI | `web/app/person_*.js`, `web/partials/person.html`, `web/person.css`, `web/locales/en.json` keys, places dialog checkbox, alerts banner, suspect styling in `trips_map.js` | C's API contract (fixture server meanwhile) |

Checklist: API 401 when locked; CLI `--json`; MCP read/write split; strings via `en.json` + `gen-honesty-json.py`;
honesty sentences untouched; <= 300 lines/file, <= 50/function; README, wiki, CHANGELOG; PRI gates.

## 13. Adversarial critique

**Person as a group, or a new entity?** Against: groups were built for quorum, so a person now carries two
semantics behind one table, and a reader of `groups` must check `kind` everywhere. A tracker in a set and in a
person raises "which event wins?". For: eight existing features come free, and existing rules keep working after
conversion. Mitigation: `kind` checks live in two places only (`groups/events.py` skip, `people/` engine); the
trigger keeps one person per tracker. Verdict: group with kind. Revisit if persons gain fields groups never need.

**Wrong inference hurts.** "Sam left" when only the bag moved is the worst failure. Motion needs two fixes. A
sibling carrying the bag (0.5 x 2 = 1.0) against Sam's parked shoes, shoes and bike (0.8) gives B/R 1.25, so
`unsure`, and `unsure` never fires. A sibling wearing Sam's shoes WOULD produce a false "Sam left"; nothing in
this data can tell. Every message names its tracker ("Seen by Sam Bag") and spells out "probably".

**Weights are made up.** They are. The override and the dry-run replay (§10.7) are the answer.

**Privacy.** A child's daily narrative on Telegram's servers and every phone in the chat is more sensitive than
a dot on a local map. Digest off by default, no coordinates in messages, per-rule chat targets (0012) limit who
reads them, and the setup says where the text goes (Q6).

**Alert fatigue.** Four kids x Home + School x arrive/leave = 16+ messages a day. One message per person
crossing, settle time, Home left-behind off, presets (Q3), and the dry-run shows the daily count first.

**False "left behind".** Bike parked at school on purpose, bag in a locker overnight. One alert per episode,
"I know" silences the day, Home off. Will still annoy on some school days.

**Ingest hold delays real arrivals** by one fix after a genuine fast trip: later, never wrong. Accepted.

**Invariant 5.** The summary reads several trackers but never draws a merged line or invents a point (Q1).

## 14. Questions for the owner (each with the default this spec builds)

1. Amend invariant 5 to "tracks are never merged; a person summary may cite several trackers but never draws a
   merged line"? Default: yes.
2. "Just arrived" only when the sighting is under 10 min old, else the time? Default: yes.
3. Default rule per new place: arrive and leave for everyone? Default: yes; presets later.
4. Left-behind alerts: on away from Home, off at Home? Default: yes, as a setting, not a per-rule flag.
5. Quiet hours (hold or drop night alerts)? Default: none in this release.
6. Daily Telegram digest: off until turned on per person, 20:00 local? Default: yes.
7. `synchronous=FULL` and daily automatic backups (7 daily, 4 weekly) in `~/.findplus/backups`? Default: yes.
8. Pets (Whiskers, Shadow) as persons of kind `pet` with the same alerts? Default: yes, alerts off by default.

# bike-tracker

A local application that builds a Google Maps Timeline-style location history for
your Google Find Hub trackers — one, several, or all of them.

Find Hub shows you the tag's *latest* position. This polls it on a schedule,
stores every distinct sighting in a local SQLite database, and serves a map and
chronological timeline in your browser.

Everything runs on this computer. Nothing is uploaded anywhere.

---

## What this is not

> This history consists of locations reported through Google's Find Hub network.
> Moto Tag uses nearby participating Android devices to report its location.
> Location updates can therefore be delayed, sparse, or unavailable, and this
> application should not be treated as real-time emergency or child-safety GPS
> tracking.

A Moto Tag 2 has no GPS and no cellular radio. It is seen when someone else's
Android phone walks past it. In a quiet area it may not be seen for hours. The
straight lines drawn between two observations are **not** the road travelled —
they are a visual connection between two known points, labelled as such
throughout the app.

## Requirements

- Python 3.12 or newer
- Google Chrome (used once, for sign-in)
- A Google account with a Find Hub tracker registered to it

## Install

```bash
git clone <this repo> bike-tracker
cd bike-tracker
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

The vendored `vendor/GoogleFindMyTools/` directory is required. If it is missing,
run `bike-tracker doctor` for repair instructions.

## First run

```bash
./.venv/bin/bike-tracker auth               # sign in with Chrome (one time)
./.venv/bin/bike-tracker devices            # list trackers on the account
./.venv/bin/bike-tracker devices --track-all # or --track <ID> --track <ID>
./.venv/bin/bike-tracker poll-now           # confirm real observations are saved
./.venv/bin/bike-tracker serve              # dashboard at http://127.0.0.1:8477
```

You can also pick trackers from the dashboard itself — the **Devices** button
opens a checklist of everything on the account.

Then, once it works, optionally install autostart:

```bash
./.venv/bin/bike-tracker install-service   # shows the exact file first, then asks
```

## Commands

| Command | What it does |
|---|---|
| `bike-tracker auth` | Interactive Google sign-in via Chrome. Re-run if the session expires. |
| `bike-tracker devices` | List devices. `--track-all`, `--track <id>` (repeatable), `--untrack <id>`, `--default <id>`. |
| `bike-tracker poll-now` | Query Find Hub once for every tracked device. |
| `bike-tracker serve` | Run the API, UI and poller in this terminal. |
| `bike-tracker start` / `stop` | Install/start, or stop/remove, the background service. |
| `bike-tracker status` | Tracker, service, schema and history summary. |
| `bike-tracker open` | Open the dashboard in your browser. |
| `bike-tracker export` | Export CSV / JSON / GPX / KML. `--device-id` narrows to one tracker. |
| `bike-tracker prune --before YYYY-MM-DD` | Delete old history. Dry run unless `--yes`. |
| `bike-tracker doctor` | Diagnose the install; report what auth material is stored and where. |

## Where things live

| What | Path |
|---|---|
| Location history | `data/bike-history.sqlite` |
| Auth material | `~/.bike-tracker/secrets.json` (mode `0600`, dir `0700`) |
| Logs (rotating) | `~/.bike-tracker/logs/bike-tracker.log` |
| Configuration | `.env` (copy from `.env.example`) |

Both the database and the secrets file are gitignored.

## Authentication, explicitly

`bike-tracker auth` opens Chrome at Google's own account-setup page. You sign in
normally, including 2FA. The app then stores:

- your Google account email
- a long-lived Android (AAS) token
- a device-manager (ADM) token
- Firebase push credentials and an Android ID
- the end-to-end-encryption owner key needed to decrypt tag locations

**Your Google password is never seen, stored, or transmitted by this
application.** Nothing here attempts to defeat Google's authentication or 2FA.

One warning: the upstream Chrome driver runs `pkill -f chrome` before launching,
so **any Chrome windows you have open will be closed** during sign-in. The `auth`
command tells you this before it starts.

If the session expires, re-run `bike-tracker auth`.

## Configuration

Copy `.env.example` to `.env`. The settings that matter most:

```ini
POLL_INTERVAL_MINUTES=5      # 5 is an enforced floor
MOVEMENT_THRESHOLD_METERS=25 # below this is treated as Bluetooth jitter
GAP_THRESHOLD_MINUTES=20     # a longer silence is drawn as a gap
RETENTION_DAYS=0             # 0 = keep history forever
```

**Do not poll faster than every 5 minutes.** The floor is enforced in code;
overriding it requires setting `ALLOW_FAST_POLLING=true`, and it risks Google
rate-limiting or flagging the account. Upstream documentation warns about this
explicitly.

The browser dashboard refreshes from the *local* API every ~45 seconds. That
never causes a Google query; Google is polled only by the server on its own
schedule.

## Tracking several devices

Any number of trackers can be polled at once — a bike tag, keys, a backpack.
Tick them in the dashboard's **Devices** dialog, or use `--track-all`.

**Each tracked device costs one Google request per poll cycle.** Three devices on
the default 5-minute interval is ~36 requests/hour. The dashboard and
`bike-tracker devices` both show the effective rate so it is never a surprise.
Devices are polled **sequentially with a 10-second stagger**, never as a burst.

One device failing never stops the others: each gets its own `poll_runs` row, and
a cycle counts as successful if at least one device reported.

**Timelines are never merged across devices.** Distance and elapsed time between
consecutive points are only meaningful within a single tracker — interleaving two
tags would invent hops between unrelated objects. The map draws one coloured
track per device and the sidebar shows independent per-device statistics. Filter
to a single tracker with the **Show** dropdown.

Untracking a device stops polling it but **keeps all of its history**.

## Deduplication

Google repeatedly returns the same last-known fix. Polling every five minutes
therefore must not create a new point every five minutes.

A sighting is identified by `(device_id, observed_at, latitude_e7, longitude_e7)`,
with a database-level unique constraint. Re-seeing an identical sighting
increments `times_returned` and updates `last_fetched_at`; it never creates a
location point. Poll health is recorded separately in `poll_runs`.

Two timestamps are kept distinct everywhere:

- `OBSERVED_AT` — when Find Hub says the tag was seen
- `FETCHED_AT` — when this computer asked

The timeline is built on `observed_at`. The dashboard shows both, plus the lag.

## Privacy

- Binds to `127.0.0.1` only. Any other bind address is refused unless you set
  `BIKE_TRACKER_ALLOW_PUBLIC_BIND=1` deliberately.
- No analytics, telemetry, cookies, cloud database, or third-party scripts.
  Leaflet is served from disk, not a CDN.
- Logs redact tokens, cookies and keys.

**One external request is unavoidable:** map tiles are fetched from
`tile.openstreetmap.org`, which therefore sees which map tiles you are viewing
(coarsely, where the bike has been). Nothing else leaves the machine. To remove
even that, point the tile URL in `web/static/app.js` at a local tile server.

## Development

```bash
./.venv/bin/python -m pytest tests/ -q     # 185 tests
./.venv/bin/ruff check src tests migrations
./.venv/bin/ruff format src tests migrations
```

Tests use mock Find Hub observations and temporary databases. They never contact
Google and never touch the real history database.

Schema changes go through Alembic:

```bash
./.venv/bin/alembic revision --autogenerate -m "description"
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the upstream audit, the reasoning
behind reusing GoogleFindMyTools rather than forking `find-hub-tracker`, the data
model, and the timezone/DST approach.

## License

GPL-3.0-or-later. This project links
[GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools) (GPL-3.0,
© Leon Böttger), vendored at commit `d46e952` with its license preserved.

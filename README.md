# Find+ (findplus)

A local application that builds a Google Maps Timeline-style location history for
your Google Find Hub trackers — one, several, or all of them.

Find Hub shows you the tag's *latest* position. This polls it on a schedule,
stores every distinct sighting in a local SQLite database, and serves a map and
chronological timeline in your browser.

Everything runs on this computer. Nothing is uploaded anywhere.

## Installation

### curl installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/acamarata/findplus/main/install.sh | bash
```

Installs Find+ into `~/.local/share/findplus/` and links `findplus` into `~/.local/bin/`.
Requires Python 3.12–3.14. Pass `--yes` to skip the confirmation prompt.

### Homebrew (macOS)

```bash
brew install acamarata/tap/findplus
```

### pip / pipx

```bash
pipx install findplus
```

Or: `pip install findplus` into an existing virtualenv.

### macOS app (dmg)

Download `FindPlus-<version>-arm64.dmg` from the [Releases](https://github.com/acamarata/findplus/releases)
page. Open the dmg and drag Find+ to Applications.

### First run

```bash
findplus auth
findplus start
```

`findplus auth` opens a Chrome window to sign in with your Google account.
`findplus start` installs a user-level LaunchAgent (macOS) or systemd service (Linux) and
opens the dashboard at http://localhost:8647.

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
git clone <this repo> findplus
cd findplus
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

The vendored `vendor/GoogleFindMyTools/` directory is required. If it is missing,
run `findplus doctor` for repair instructions.

Apple Find My support is an optional extra: `./.venv/bin/pip install -e ".[apple]"`.

## First run

```bash
./.venv/bin/findplus auth               # sign in with Chrome (one time)
./.venv/bin/findplus devices            # list trackers on the account
./.venv/bin/findplus devices --track-all # or --track <ID> --track <ID>
./.venv/bin/findplus poll-now           # confirm real observations are saved
./.venv/bin/findplus serve              # dashboard at http://127.0.0.1:8647
```

You can also pick trackers from the dashboard itself — the **Devices** button
opens a checklist of everything on the account.

Then, once it works, optionally install autostart:

```bash
./.venv/bin/findplus install-service   # shows the exact file first, then asks
```

## Commands

| Command | What it does |
|---|---|
| `findplus auth` | Interactive Google sign-in via Chrome. Re-run if the session expires. |
| `findplus devices` | List devices. `--track-all`, `--track <id>` (repeatable), `--untrack <id>`, `--default <id>`. |
| `findplus poll-now` | Query Find Hub once for every tracked device. |
| `findplus serve` | Run the API, UI and poller in this terminal. |
| `findplus start` / `stop` | Install/start, or stop/remove, the background service. |
| `findplus status` | Tracker, service, schema and history summary. |
| `findplus open` | Open the dashboard in your browser. |
| `findplus export` | Export CSV / JSON / GPX / KML. `--device-id` narrows to one tracker. |
| `findplus prune --before YYYY-MM-DD` | Delete old history. Dry run unless `--yes`. |
| `findplus doctor` | Diagnose the install; report what auth material is stored and where. |

## Where things live

| What | Path |
|---|---|
| Location history | `data/findplus.sqlite` |
| Auth material | `~/.findplus/secrets.json` (mode `0600`, dir `0700`) |
| Logs (rotating) | `~/.findplus/logs/findplus.log` |
| Configuration | `.env` (copy from `.env.example`) |

Both the database and the secrets file are gitignored.

## Authentication, explicitly

`findplus auth` opens Chrome at Google's own account-setup page. You sign in
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

If the session expires, re-run `findplus auth`.

## Apple Find My

Apple Find My locations come from nearby Apple devices and can be delayed,
sparse or unavailable. Find+ can only query accessories whose keys you hold;
genuine AirTags require extracting pairing keys, which most users cannot do.

Find+ is not affiliated with Apple or Google. Find Hub and Find My are their
trademarks.

Install the extra, register an accessory, then authenticate:

```bash
./.venv/bin/pip install -e ".[apple]"
./.venv/bin/findplus apple add-accessory "Wallet Tag" --private-key <base64>
./.venv/bin/findplus auth --provider apple-find-my
```

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
`findplus devices` both show the effective rate so it is never a surprise.
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

## App lock

Settings → **App lock** sets a PIN (or a passphrase). Once enabled, opening the
dashboard shows a lock screen; unlocking returns you to exactly the view you
were on — same day, same device filter, same selected point, same scroll
position.

- **Enforced on the server, not in the browser.** While locked, every data
  endpoint returns `401`. The dashboard is not merely hidden behind an overlay —
  the history cannot be retrieved with `curl` either.
- Auto-locks after a configurable idle period (default 15 minutes; `Never` is an
  option), and whenever the service restarts or the machine reboots.
- The PIN is stored only as a salted **scrypt** hash. Five wrong attempts trigger
  a 60-second lockout, which applies to the correct PIN too.
- Changing the PIN signs out every other browser but keeps you signed in where
  you changed it.
- Forgot it? `findplus reset-lock`. There is no cloud reset by design.

**Be clear about what this does.** The lock stops another person at this computer
from browsing your history. It does **not** encrypt the database — anyone with
access to this user account or the disk can read `data/findplus.sqlite`
directly. Use FileVault if you need protection at rest.

## Deleting history

History is never deleted silently. Settings → **Delete history** offers:

- **Delete older than…** — pick a date; it tells you how many observations would
  go and asks before removing them.
- **Clear ALL history** — shows the count, asks for confirmation, then requires
  you to type `DELETE`.

From the CLI, `findplus prune --before YYYY-MM-DD` is a dry run unless you
pass `--yes`.

## Themes

Dark (default), Light, or Match system. Set it in Settings, or with
`findplus theme light`. The choice is stored server-side, so it follows you
across browsers, and is cached locally so there is no flash on load.

## Keeping it running

Two independent jobs, both user-level:

| Job | Role |
|---|---|
| `com.acamarata.findplus` | The service. `RunAtLoad` starts it at login; `KeepAlive` restarts it if the process dies. |
| `com.acamarata.findplus.watchdog` | Every 5 minutes, asks the local API whether it is alive. If not, restarts the service. |

`KeepAlive` only sees a process that has *died*. The watchdog covers the other
failure mode: a process that is alive but wedged. A `401` from the app lock
counts as healthy, so enabling the lock does not cause restart loops.

Check both with `findplus status`.

## Privacy

- Binds to `127.0.0.1` only. Any other bind address is refused unless you set
  `FINDPLUS_ALLOW_PUBLIC_BIND=1` deliberately.
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

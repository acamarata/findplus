# Backup and restore

Your history lives in one SQLite file, `~/.findplus/findplus.sqlite`. Find+ keeps
recent copies of it, checks it for damage, and can export everything you built
into a plain file you can read.

## Automatic backups

While the daemon runs it makes one backup a day, and one at startup if the newest
is a day old or more. Backups go to `~/.findplus/backups/` as
`findplus-YYYYMMDD-HHMMSS.sqlite` (UTC time).

- Each copy is made with SQLite's online backup, so it is consistent even while
  Find+ is saving new sightings. It is not a file copy of a live database.
- Each copy is opened and checked before it is kept. A copy that fails its check
  is thrown away and the failure is logged.
- Find+ keeps the newest backup of each of the last 7 days, plus the newest of
  each of the 4 weeks before that. Older automatic backups are deleted. Backups
  you make yourself, and the pre-restore backup below, are never deleted for you.
- The folder is private (mode 0700) and every backup is 0600.
- A backup holds the database only. Your sign-in tokens (`secrets.json`), alert
  channel settings (`alerts.json`) and Apple keys live elsewhere and are never
  copied into a backup. Back those up yourself if you want them.

Change where backups go and how many are kept in the dashboard's settings
(`PATCH /api/settings`: `backup.directory`, `backup.keep_daily`,
`backup.keep_weekly`) or with the CLI:

```
findplus config set backup_dir /Volumes/Backup/findplus
findplus config set backup_keep_daily 14
findplus config set backup_keep_weekly 8
```

Putting the folder on another disk is the single best upgrade: a backup on the
same disk does not survive that disk failing.

## By hand

```
findplus db backup            # a verified copy now, kept until you delete it
findplus db backups           # list them, newest first (--json for scripts)
findplus db check             # quick, integrity and foreign-key checks
```

`findplus doctor` runs the same checks and also says if backups have stopped
(newest older than three days) or are readable by other users
(`findplus doctor --repair` fixes the permissions).

## Restore

```
findplus stop
findplus db restore ~/.findplus/backups/findplus-20260930-120000.sqlite
findplus start
```

Restore is built not to make things worse:

1. It checks the file first: a SQLite file, passes its own checks, made by a
   Find+ no newer than this one.
2. It refuses while Find+ is running (use `--force` only if you are sure).
3. It takes a pre-restore backup of the current database
   (`findplus-prerestore-...sqlite`).
4. It builds the new file beside the old one and checks it.
5. It keeps the file it replaces as `findplus.sqlite.replaced-<time>`. Nothing is
   deleted. Delete it yourself when you are happy.
6. It upgrades the restored file to the current schema.

## If the database is damaged

At startup Find+ runs a quick check. If it finds damage, the daemon starts
read-only: the dashboard shows "Find+ found damage in its history database, so
it is read-only for now. Nothing has been deleted.", and Find+ does not poll,
prune or write. The damaged file is left exactly as it was. Restore a backup as
above.

## Take your data out, bring it back

```
findplus export --format jsonl -o everything.jsonl
findplus import everything.jsonl        # into an empty database only
```

The JSONL file has one JSON object per line: a header (format version, Find+
version, schema revision, counts), then devices, places, groups (with their kind
and members), observations and alert rules. It is meant to be read by people as
well as by Find+. Alert rules refer to places and groups by name. The file never
includes your PIN hash, sign-in tokens or channel secrets. Quality flags, place
events and delivery logs are not exported; they are worked out again. After an
import run `findplus db recompute-quality`.

Import refuses a database that already has data. Use a fresh state directory
(`FINDPLUS_STATE_DIR=/tmp/new findplus import file.jsonl`).

## Why SQLite with these settings

Find+ stays on SQLite in WAL mode: one file, transactional, no server, right for
one person's location history. Since 1.1.6 every commit is synced to disk
(`PRAGMA synchronous=FULL`) rather than only at checkpoints, because a sighting
cannot always be fetched again. The cost is one extra
disk sync per commit. Measured on a Mac SSD, 1,000 single-row commits took 0.04
seconds with FULL and 0.01 seconds with NORMAL, and a poll makes a few commits,
so the cost does not show. One honest limit: macOS syncs to the drive, not
necessarily through the drive's own write cache, unless SQLite's `fullfsync` is
on. Find+ does not turn that on, so a power cut can still lose the last moments
on some drives. Backups are the answer to that, not the pragma.

The app lock stops casual browsing; it does not encrypt this file or its
backups. Use FileVault. See [App lock](App-lock).

---
[[Home]]

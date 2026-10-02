# Settings

Open the dialog from the **Settings** button in the toolbar, or go straight to
`http://localhost:8647/#settings`.

## Sign in

The first section of the dialog shows each provider, the account you are signed
in as, and what is still missing. **Connect** opens Google's sign-in in a Find+ window that closes itself, or Apple's
in one sheet. A sign-in that has stopped working shows a **Sign in again** button
here. See [Sign in](Sign-in).

## Polling interval

**Poll every N minutes** sets how often Find+ asks your providers where your
trackers are. Anything from 5 to 1440 minutes is accepted.

> Find+ never polls faster than every 5 minutes, to avoid rate-limiting your account.
> Takes effect after Find+ restarts.

The floor is not arbitrary: polling faster gets accounts rate-limited, and Find
Hub sightings do not arrive faster than that anyway. The new value is written to
`~/.findplus/config.env` straight away, but the running poller keeps the interval
it started with, so restart Find+ for it to take effect. If
`FINDPLUS_POLL_INTERVAL_MINUTES` is set in the environment, that value wins and
the box goes on showing the one actually in force.

## History retention

**Keep history for N days** sets how far back Find+ keeps data. The minimum is 7
days. Leave the field blank to keep everything forever.

> Older observations, place visits and group events are deleted automatically once a day.
> Leave blank to keep everything.

This is a background job inside the daemon, not something you run. It re-reads
its setting every cycle, so a change needs no restart. It is a different thing
from `findplus prune`, which is a manual one-shot you run yourself against a
date you choose.

## Backups

Find+ backs up its database once a day. **Backup folder**, **Daily backups kept**
(1 to 60, default 7) and **Weekly backups kept** (0 to 52, default 4) are the
`backup.directory`, `backup.keep_daily` and `backup.keep_weekly` keys of
`GET/PATCH /api/settings`, and `backup_dir`, `backup_keep_daily` and
`backup_keep_weekly` in `findplus config set`. They take effect on the next
backup. A folder must be a full path. Send `null` for `backup.directory` to go
back to `~/.findplus/backups`. See [Backup and restore](Backup-and-restore).

## Notification detail

**Show who and where in notifications** appears only in the macOS app, and is
off by default. The dialog shows the reason next to the tick box, and the daemon
serves the same sentence at `GET /api/config` under `notices.native_generic`:

> By default, macOS notifications show a generic "Find+ alert" instead of who or
> where, because notification banners can appear on a locked screen. Turn on
> notification details in Settings to show the person and place. Anyone who can see
> the screen then sees the same thing.

While Find+ itself is locked the generic wording is used whatever this is set
to.

## Appearance, desktop and app lock

Theme is dark, light, or follow the system. **Start Find+ at login** installs or
removes the user-level service. The app lock takes a PIN of at least six
characters and can lock after an idle period. See [App lock](App-lock) for what
it does and does not protect.

## People: daily summary, left-behind alerts, backup

The daily summary is off until you turn it on. Pick the time, the channel (Telegram), and whose
day to send; **Send now** sends today. The message is words only, with no coordinates, and goes to
the chat you chose, so anyone who reads that chat reads it. Turning the last person off turns the
summary off.

The left-behind switch controls whether "Sam's bag looks left at School" becomes an alert. It
never fires at a Home place.

The backup line shows the time of the newest backup and how many are kept. **Back up now** takes a
verified copy of the database (not your sign-ins or tokens). See [Backup and
restore](Backup-and-restore).

## Delete history

Delete observations before a date, or clear everything. Both tell you how many
rows would go and ask again before removing anything.

## About

Version, schema revision, timezone and poll interval, plus **Run setup again**.

**Run setup again** reopens the eight-step [first-run wizard](First-run) at the
step it last left off. It resets nothing: everything you have already saved
stays saved, and the setup is only marked finished again when you reach the
wizard's Done step. Abandoning a re-run leaves a finished setup finished.

---
[[Home]]

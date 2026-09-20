# Settings

Open the dialog from the **Settings** button in the toolbar, or go straight to
`http://localhost:8647/#settings`.

## Polling and retention

**Poll every N minutes** sets how often Find+ asks your providers where your
trackers are. The floor is 5 minutes: polling faster gets accounts rate-limited,
and Find Hub sightings do not arrive faster than that anyway. The change is
written to `~/.findplus/config.env` straight away, but the running poller keeps
the interval it started with, so restart Find+ for it to take effect. If
`FINDPLUS_POLL_INTERVAL_MINUTES` is set in the environment, that value wins and
the box goes on showing the one actually in force.

**Keep history for N days** prunes location observations, place visits and group
events older than the window, once a day. Leave it blank to keep everything
forever. Retention re-reads its setting every cycle, so it needs no restart.

**Show who and where in notifications** appears only in the macOS app, and is
off by default. Left off, a notification says only "Find+ alert", because a
banner can appear on a locked screen. Turn it on and the banner names the person
and the place, which means anyone who can see the screen sees the same thing.
While Find+ itself is locked the generic wording is used whatever this is set
to. The dialog shows the exact sentence next to the tick box, and the daemon
serves it at `GET /api/config` under `notices.native_generic`.

## Sign-in

The first section of the dialog shows each provider, the account you are signed
in as, and what is still missing. Signing in here is the same flow
`findplus auth` runs in the terminal.

## Appearance, desktop and app lock

Theme is dark, light, or follow the system. **Start Find+ at login** installs or
removes the user-level service. The app lock takes a PIN of at least six
characters and can lock after an idle period; it stops casual browsing of the
dashboard, and is not encryption.

## Delete history

Delete observations before a date, or clear everything. Both tell you how many
rows would go and ask again before removing anything.

## About

Version, schema revision, timezone and poll interval, plus **Run setup again**,
which reopens the first-run wizard wherever it last left off. Reopening it
changes nothing by itself: the setup is only marked finished again when you
reach the wizard's Done step.

---
[[Home]]

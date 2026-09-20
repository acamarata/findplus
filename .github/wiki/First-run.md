# First run

One command on a signed-in account, or two from scratch:

```bash
findplus setup
```

`findplus setup` walks you through sign-in, device selection, groups,
notifications and the app lock in the terminal, then stamps the setup as
finished. Pass `--yes` to accept every default and skip every optional step,
which is what `install.sh --start` does.

## In the dashboard

The first time you open the dashboard it goes straight to a setup wizard:
welcome, sign-in, devices, groups, places, notifications, the app lock, and a
summary. Every step after the first can be skipped, and skipping one changes
nothing. Close the tab halfway through and the next visit picks up on the step
you were on.

If you navigate somewhere else before finishing, a bar under the toolbar offers
to resume it. Dismissing the bar hides it for that tab only; it comes back on
the next load until you reach the wizard's Done step. You can reopen the wizard
at any time from Settings, under About, with **Run setup again**.

## Manual path

```bash
findplus auth
findplus start
```

`findplus auth` opens Chrome to sign in with your Google account (or runs an
interactive Apple sign-in with `--provider apple-find-my`). `findplus start`
then discovers your devices, tracks them, installs a user-level service, begins
polling, and opens the dashboard at http://localhost:8647 in your browser
automatically. Run it before signing in and it stops with exit code 4 and tells
you which command to run first.

![Dashboard](https://raw.githubusercontent.com/acamarata/findplus/main/.github/docs/screenshots/dashboard-light.png)

From the dashboard, open **Devices** to choose which trackers to follow, or
run `findplus devices --track-all` from the CLI. Add a place from the map
with the crosshair tool, and set up alerts from the Alerts tab.

If the browser does not open on its own, run `findplus open`.

---
[[Home]]

# Updates

The macOS app keeps itself up to date. You do not need to download anything or run a script.

## What happens

1. About every six hours Find+ asks GitHub's releases API for the newest release of
   `acamarata/findplus`. Drafts and pre-releases are ignored.
2. When a newer version exists, the app downloads its disk image from the same GitHub release into
   `~/.findplus/updates/` and checks it against the sha256 published beside it. A download that
   does not match is deleted and nothing is installed.
3. When you have not used Find+ for a few minutes (no Find+ window open for 5 minutes, or a window
   left open but unused for 30), Find+ installs the update:
   - it takes a verified backup of the database (`findplus-preupdate-<time>.sqlite` in your backup
     folder, see [Backup and restore](Backup-and-restore));
   - it checks the new app: Apple Silicon, a valid code signature, and signed by the same developer
     (Team ID) as the app you have. A new app from anyone else is refused;
   - it quits, swaps `Find+.app` and starts again on the new version.
4. On its first start the new version upgrades the database schema, after taking one more backup
   of the database as the old version left it.

Your history, settings, sign-ins and backups live in `~/.findplus`, outside the app. An update
never moves or changes them.

If an update cannot be installed (the check fails, or the swap fails), the app you had stays in
place and starts again. Find+ does not retry that same build by itself; **Update now** tries again.

## While you are using it

If Find+ is in use when an update is ready, it waits. Until then:

- the menu bar menu shows **Restart to update (vX)**;
- the dashboard shows a small **Restart to update** button in the bottom right corner (**Later**
  hides it until the page reloads).

Either one installs the update straight away, with the same backup and checks.

## Settings

**Settings > Updates** shows the installed version, the newest one found and when Find+ last
checked. It has:

- **Update Find+ automatically** (on by default). Off: Find+ makes no update request at all
  unless you press **Check now**.
- **Check now**: ask GitHub straight away.
- **Update now** (in the app, when an update is ready): install it now.

From the terminal:

```bash
findplus update status     # installed version, what was found, any problem
findplus update check      # ask GitHub now
findplus update auto off   # no update requests; `on` turns them back on
```

## What is sent

> Automatic updates ask GitHub's releases API for the newest Find+ about every six
> hours and download a new version from the same GitHub release. The request names
> only the Find+ version; nothing about you, your trackers or your history is sent,
> though GitHub sees this computer's IP address. Turn automatic updates off to stop
> these requests.

## Outside the app

The CLI (`pipx`, Homebrew, `install.sh`) and a dashboard opened in a browser only report that a
new version exists; they never install anything. Update those with `brew upgrade findplus` or by
running `install.sh` again. The dashboard links to the release notes.

To update the app by hand, see [macOS app](macOS-app#updating).

## For developers: a folder of local builds

Point Find+ at a folder that holds your own builds, and the app installs each new build by itself,
with the same backup, checks and restart as a release:

```bash
findplus update dev-dir ~/Sites/acamarata/findplus/desktop/src-tauri/target/release/bundle
findplus update dev-dir --clear   # back to releases only
```

(`FINDPLUS_UPDATE_DEV_DIR` does the same and wins over the setting; `updates.dev_dir` in
`PATCH /api/settings` too.) Off by default.

- Find+ looks for `Find+.app` in the folder or its `macos/` subfolder, and for
  `FindPlus-<version>-aarch64.dmg` with its `.sha256` beside it. A build changed in the last two
  minutes is skipped until it settles.
- A build is installed when its version is newer than the running one, or when it is a new build of
  the same version (Find+ remembers a fingerprint of the last build it installed).
- A GitHub release with a higher version than your build wins.
- The build must be signed by the same Team ID as the installed app; an ad-hoc or unsigned build is
  refused over a signed install. The folder is only read, never changed.

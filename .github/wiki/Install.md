# Install

## curl installer (macOS, Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/acamarata/findplus/main/install.sh | bash
```

Installs Find+ into `~/.local/share/findplus/` and links `findplus` into
`~/.local/bin/`. Requires Python 3.12, 3.13 or 3.14. Pass `--yes` to skip the
confirmation prompt, or `--uninstall` to remove it (see [Uninstall](Uninstall)
for what that keeps and what it removes).

`~/.local/bin` is not on the default PATH on macOS, and on Debian and Ubuntu
`~/.profile` adds it only if the directory already existed when you logged in.
If it is not on yours, the installer says so and prints the line to add; until
you add it, `~/.local/bin/findplus` works by full path.

On Debian and Ubuntu the `venv` module ships separately from `python3`. If it
is missing the installer names the exact package to install
(`sudo apt install python3.12-venv`) rather than the Python version.

Re-running the installer upgrades an existing install. If its virtualenv was
broken by an OS upgrade or a removed Python, re-running rebuilds it.

## pipx

Find+ is not published to PyPI. Install the wheel from the latest release
instead. Download the `findplus-<version>-py3-none-any.whl` from the
[Releases](https://github.com/acamarata/findplus/releases) page (for example, v1.1.5):

```bash
pipx install https://github.com/acamarata/findplus/releases/download/v1.1.5/findplus-1.1.5-py3-none-any.whl
```

Or install from the latest release directly:

```bash
gh release download --repo acamarata/findplus --pattern '*.whl' && pipx install findplus-*.whl
```

`pip install` with the same URL works inside an existing virtualenv.

## Homebrew (macOS)

```bash
brew install acamarata/tap/findplus
```

`brew upgrade findplus` picks up each new release once the tap formula is updated.

## macOS app (dmg)

Download `FindPlus-<version>-aarch64.dmg` from the
[Releases](https://github.com/acamarata/findplus/releases) page. Open the
dmg and drag Find+ to Applications. The app bundles the daemon, so no
separate CLI install is required.

The app is built for Apple Silicon only. On an Intel Mac, install with
Homebrew or the curl installer above and open the dashboard in your browser
at http://127.0.0.1:8647.

## Chrome helper

Every install route above (curl, pipx, Homebrew, dmg) needs the Find+ Chrome
helper for Google sign-in. Add it once: open the sign-in card in the dashboard,
click **Show helper folder**, then **Open Chrome extensions**, turn on Developer
mode and choose Load unpacked. See [Chrome helper privacy](Chrome-helper-privacy)
for what it reads.

## Updating the macOS app

Run this while Find+ is open; it quits the app, swaps it and starts it again. Your history,
settings and `~/.findplus/backups/` are not touched.

```bash
curl -fsSL https://github.com/acamarata/findplus/releases/latest/download/update-app.sh | bash
```

`update-app.sh` checks the dmg against the sha256 published on the same release.
That detects a corrupted download only. It does not authenticate the release, so
it is no protection against a release that was itself tampered with.

## Where your data goes

Everything lives in `~/.findplus/`: the database, secrets, logs and a daily backup folder,
`~/.findplus/backups/`. Backups are unencrypted copies of the database (with the app-lock PIN hash,
never sign-in tokens). Upgrading never touches them. See [Backup and
restore](Backup-and-restore).

## Post-install

Run `findplus setup` for a guided walkthrough (or `findplus auth` then
`findplus start` for the two-command path), then continue with
[First run](First-run).

To remove Find+ later, see [Uninstall](Uninstall).

---
[[Home]]

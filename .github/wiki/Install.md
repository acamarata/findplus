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

```bash
pipx install findplus
```

Or `pip install findplus` into an existing virtualenv.

## Homebrew (macOS)

```bash
brew install acamarata/tap/findplus
```

Available after the 1.0 release via `brew install acamarata/tap/findplus`.

## macOS app (dmg)

Download `FindPlus-<version>-aarch64.dmg` from the
[Releases](https://github.com/acamarata/findplus/releases) page. Open the
dmg and drag Find+ to Applications. The app bundles the daemon, so no
separate CLI install is required.

## Post-install

Run `findplus setup` for a guided walkthrough (or `findplus auth` then
`findplus start` for the two-command path), then continue with
[First run](First-run).

To remove Find+ later, see [Uninstall](Uninstall).

---
[[Home]]

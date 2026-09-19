# Install

## curl installer (macOS, Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/acamarata/findplus/main/install.sh | bash
```

Installs Find+ into `~/.local/share/findplus/` and links `findplus` into
`~/.local/bin/`. Requires Python 3.12 or newer. Pass `--yes` to skip the
confirmation prompt, or `--uninstall` to remove it.

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

Run `findplus auth` to sign in, then continue with [First run](First-run).

---
[[Home]]

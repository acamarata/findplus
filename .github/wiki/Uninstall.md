# Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/acamarata/findplus/main/install.sh | bash -s -- --uninstall
```

That unloads the service and the watchdog, then removes the venv under
`~/.local/share/findplus/` and the `findplus` symlink in `~/.local/bin/`.
Your history stays: the state directory `~/.findplus/` is left untouched, so
delete it yourself if you want the database and settings gone too.

## Removing the service by hand

`install.sh --uninstall` prints these same commands when the `findplus`
binary is already gone and it cannot unload the service for you. Run the set
for your platform.

**macOS**

```bash
launchctl bootout gui/$(id -u)/com.acamarata.findplus
launchctl bootout gui/$(id -u)/com.acamarata.findplus.watchdog
rm -f ~/Library/LaunchAgents/com.acamarata.findplus*.plist
```

**Linux**

```bash
systemctl --user disable --now findplus.service findplus-watchdog.timer
rm -f ~/.config/systemd/user/findplus*
```

**Windows**

```bat
schtasks /delete /tn FindPlus /f
schtasks /delete /tn FindPlusWatchdog /f
```

Nothing here needs sudo or an administrator shell: Find+ only ever installs
user-level jobs.

---
[[Install]] · [[Home]]

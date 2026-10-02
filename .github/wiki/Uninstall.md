# Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/acamarata/findplus/main/install.sh | bash -s -- --uninstall
```

That unloads the service and the watchdog, then removes the venv under
`~/.local/share/findplus/` and the `findplus` symlink in `~/.local/bin/`.
Your history stays: the state directory `~/.findplus/` is left untouched, so
delete it yourself if you want the database and settings gone too. That includes
`~/.findplus/backups/`, which holds unencrypted copies of your history (and the app-lock PIN
hash). Removing only the database file leaves those copies behind; to remove them all, run
`rm -r ~/.findplus/backups` (or the `findplus-backups` folder inside the backup folder you chose).

## Older versions left a Chrome profile

Find+ 1.1 and earlier signed in through a separate Chrome window with its own
profile at `~/.findplus/chrome-profile`. Version 1.2 hides that window and does
not use the folder, but it may still be on your disk from an upgrade. It holds
cookies and history of those sign-ins only, not your everyday Chrome profile.
With Find+ and that Chrome window closed, delete it:

```bash
rm -r ~/.findplus/chrome-profile
```

Find+ will make a new one only if you ask for the terminal's own-Chrome sign-in
(`findplus auth` or `findplus auth --unlock`) again. If you added the Chrome
helper, remove it at `chrome://extensions` and delete
`~/.findplus/chrome-helper`.

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

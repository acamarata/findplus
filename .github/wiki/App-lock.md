# App lock

Settings -> **App lock** sets a PIN. Once enabled, opening the dashboard
shows a lock screen; unlocking returns you to exactly the view you were on.

- Enforced on the server, not in the browser: while locked, every data
  endpoint returns `401`. The history cannot be retrieved with `curl`
  either.
- Auto-locks after a configurable idle period (default 15 minutes, or
  never), and whenever the service restarts or the machine reboots.
- The PIN is stored only as a salted scrypt hash. Five wrong attempts
  trigger a 60-second lockout, which applies to the correct PIN too.
- Forgot it? `findplus reset-lock --yes` removes the lock from this
  machine. There is no cloud reset by design.

## What this does not do

The app lock stops casual browsing. It does not encrypt the database;
anyone with access to this user account or the disk can read it. Use
FileVault.

Enable FileVault (System Settings -> Privacy & Security -> FileVault) for
protection when the disk itself is at risk, such as a lost or stolen
machine.

---
[[Home]]

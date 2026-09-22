# Privacy and threat model

## Where data lives

All data is stored in `~/.findplus/` (SQLite database, secrets, logs). There
is no cloud sync and no telemetry. Secrets (`secrets.json`, `alerts.json`,
`apple-account.json`) are written at file mode `0600` inside a `0700`
directory, and never appear in the database or logs.

## The six notices, verbatim

> This history consists of locations reported through Google's Find Hub
> network. Your trackers use nearby participating Android devices to report their
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

Apple Find My locations come from nearby Apple devices and can be delayed,
sparse or unavailable. Find+ can only query accessories whose keys you
hold; genuine AirTags require extracting pairing keys, which most users
cannot do.

Alerts inherit the network's delay. An arrival or departure may be reported
minutes to hours late.

A tag with no recent fix is stale, not at home and not left behind. Find+
reports it as unknown.

The app lock stops casual browsing. It does not encrypt the database;
anyone with access to this user account or the disk can read it. Use
FileVault.

Find+ is not affiliated with Apple or Google. Find Hub and Find My are their
trademarks.

## Threat model

| Threat | Mitigation |
|---|---|
| Physical access to this machine while unlocked | Enable the app lock; auto-locks on idle and reboot. |
| Disk access (stolen drive, another OS booted from it) | Use FileVault. The app lock does not protect data at rest. |
| Account access (your Google or Apple account is compromised) | Find+ stores tokens locally; revoking the app's access on the provider side stops further polling. |
| Someone on your network | Find+ binds to `127.0.0.1` only, refused elsewhere unless `FINDPLUS_ALLOW_PUBLIC_BIND=1` is set. |
| A malicious web page in your browser (DNS rebinding, cross-site requests) | The API validates the request's Host/Origin against the expected loopback address *and port* and rejects anything else, so a page from another origin cannot reach it even by resolving a hostname to 127.0.0.1, and cannot bypass the check by naming a different port. |

## Local API surface

The daemon listens on `127.0.0.1:8647` only. Every state file it writes
under `~/.findplus/` (the database, `secrets.json`, `alerts.json`,
`apple-account.json`, and `apple/*.json`) is created at file mode `0600`
inside a `0700` directory. Binding to any other address, or accepting a
request whose Host or Origin header does not match the loopback address
on the daemon's own port, is refused by default. A Host or Origin naming
the right loopback address but a different port is refused the same as a
foreign one, so a page that rebinds a hostname to 127.0.0.1 cannot pick
its own port to get past the check.

---
[[Home]]

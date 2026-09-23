# Home

Local location history for Google Find Hub and Apple Find My trackers.

Find+ polls your Find Hub and Find My accounts on a schedule, stores every
distinct sighting in a local SQLite database, and serves a map, timeline,
places, groups, and alerts through a browser dashboard, a CLI, a REST API,
and an MCP server. Everything runs on this computer. Your location history
stays on this machine. Map tiles always load from OpenStreetMap; anything
else leaves only when you turn it on: signing in to Google or Apple, address
search, and any alert channel you connect (Telegram, WhatsApp or a webhook).
See [Privacy and threat model](Privacy-and-threat-model).

## Get started

- [Install](Install): curl installer, Homebrew, pipx, or the macOS app.
- [First run](First-run): the eight-step setup wizard, in the dashboard or the terminal.
- [Sign in](Sign-in): connect Google or Apple from the dashboard.
- [Devices and groups](Devices-and-groups): track trackers, form groups.
- [Places and alerts](Places-and-alerts): geofences and notifications.
- [Settings](Settings): poll interval, history retention, app lock, notifications.
- [CLI reference](CLI-reference)
- [API reference](API-reference)
- [MCP](MCP): connect Find+ to Claude Desktop or Claude Code.
- Fresh-machine rehearsal: `.github/docs/REHEARSAL.md` in the repo records the install, reinstall and uninstall run that was verified before release.
- First-run screenshots: `.github/docs/screenshots/setup/` in the repo (16 shots, 1280px and 375px, from the scripted wizard rehearsal).

## Notices

> This history consists of locations reported through Google's Find Hub
> network. Your trackers use nearby participating Android devices to report their
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

Apple Find My locations come from nearby Apple devices and can be delayed,
sparse or unavailable. Find+ can only query accessories whose keys you hold;
genuine AirTags require extracting pairing keys, which most users cannot do.

Find+ is not affiliated with Apple or Google. Find Hub and Find My are their
trademarks.

---
[[Home]]

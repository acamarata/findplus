# Home

Local location history for Google Find Hub and Apple Find My trackers.

Find+ polls your Find Hub and Find My accounts on a schedule, stores every
distinct sighting in a local SQLite database, and serves a map, timeline,
places, groups, and alerts through a browser dashboard, a CLI, a REST API,
and an MCP server. Everything runs on this computer. Nothing is uploaded
anywhere except the location queries themselves, which go to Google or
Apple's own network.

## Get started

- [Install](Install): curl installer, Homebrew, pipx, or the macOS app.
- [First run](First-run): sign in and start the daemon.
- [Devices and groups](Devices-and-groups): track trackers, form groups.
- [Places and alerts](Places-and-alerts): geofences and notifications.
- [CLI reference](CLI-reference)
- [API reference](API-reference)
- [MCP](MCP): connect Find+ to Claude Desktop or Claude Code.

## Notices

> This history consists of locations reported through Google's Find Hub
> network. Moto Tag uses nearby participating Android devices to report its
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

# findplus (Find+ CLI and daemon)

The Python core of [Find+](https://github.com/acamarata/findplus): a local, privacy-first location history
for Google Find Hub and Apple Find My trackers, with named places, device groups and alerts. This package
provides the `findplus` command, the background daemon, the local REST API at `http://localhost:8647`, the
dashboard and the MCP server.

Install: `pipx install findplus` (or `brew install acamarata/tap/findplus`, or the `install.sh` in the
repository). First run: `findplus auth` then `findplus start`.

Locations come from crowdsourced networks and can be delayed, sparse or unavailable. Find+ is not
real-time GPS tracking and is not affiliated with Apple or Google. Full documentation, licence
(GPL-3.0-or-later) and source: https://github.com/acamarata/findplus

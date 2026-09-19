# FAQ

**Does it work without internet?**
Polling needs a network connection to query Google or Apple. The dashboard
itself, and everything already in the database, works offline.

**Is location data sent anywhere?**
No. Find+ queries Google's or Apple's own network for your tag's location
and stores the result locally in `~/.findplus/`. Nothing is sent to any
Find+ server, because there is no Find+ server.

**Does it work with AirTags?**
Only accessories whose keys you hold. Genuine AirTags require extracting
pairing keys from a device that has already paired with them, which most
users cannot do.

**What is Find Hub?**
Google's crowdsourced tracker network (formerly Find My Device), which
Moto Tag and compatible trackers use. Nearby Android devices relay a tag's
location back to its owner's account.

**Can I track multiple people or devices at once?**
Yes, using groups. A group of devices reports a combined presence verdict
(together, apart, partial, or unknown) based on a configurable quorum rule.

**How do I uninstall?**
`findplus uninstall --yes` removes the service and watchdog unit files.
Remove `~/.findplus/` by hand if you also want to delete your history.

**What is the MCP server?**
An [MCP](https://modelcontextprotocol.io) endpoint (`findplus mcp`) that
lets an LLM client such as Claude Desktop or Claude Code query your
location history, places, and groups as tools.

**Is Find+ affiliated with Apple or Google?**
Find+ is not affiliated with Apple or Google. Find Hub and Find My are
their trademarks.

---
[[Home]]
